"""Assimilation pipeline for CAM-PULSE discoveries.

Clones discovered repos, runs them through RepoMiner, and stores
findings in claw.db via the existing memory pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from claw.core.config import ClawConfig
from claw.db.engine import DatabaseEngine
from claw.miner import RepoMiner, RepoMiningResult
from claw.pulse.models import AssimilationResult, PulseDiscovery

if TYPE_CHECKING:
    from claw.security.scanner import ScanResult

logger = logging.getLogger("claw.pulse.assimilator")


class PulseAssimilator:
    """Clones and mines discovered repos, stores results in claw.db."""

    def __init__(
        self,
        engine: DatabaseEngine,
        miner: RepoMiner,
        config: ClawConfig,
    ):
        self.engine = engine
        self.miner = miner
        self.config = config
        self._workspace = Path(config.pulse.clone_workspace)

    async def assimilate(
        self,
        discovery: PulseDiscovery,
        target_project_id: str,
    ) -> AssimilationResult:
        """Clone -> mine -> store -> update status.

        Routes HuggingFace URLs to assimilate_hf_repo() automatically.

        Args:
            discovery: The PulseDiscovery to assimilate.
            target_project_id: Project ID for storing findings.

        Returns:
            AssimilationResult with success status and methodology IDs.
        """
        # Route HF URLs to the HF-specific pipeline
        if "huggingface.co/" in discovery.canonical_url:
            repo_id = discovery.canonical_url.replace(
                "https://huggingface.co/", ""
            ).strip("/")
            return await self.assimilate_hf_repo(
                repo_id=repo_id,
                target_project_id=target_project_id,
            )

        result = AssimilationResult(discovery=discovery)

        # Update status to 'cloning'
        await self._update_discovery_status(discovery.canonical_url, "cloning")

        clone_path: Optional[Path] = None
        try:
            # 1. Clone
            clone_path = await self._clone_repo(discovery.canonical_url)

            # 1b. Capture HEAD SHA before mining (clone_path will be cleaned up in finally)
            head_sha = await self._get_head_sha(clone_path)

            # 1c. Pre-mine secret scan (Gate 1)
            secret_scan_files: set[str] | None = None
            if self.config.security.secret_scan_enabled:
                await self._update_discovery_status(discovery.canonical_url, "scanning")
                scan_result = await self._scan_for_secrets(clone_path)
                result.scan_result = scan_result
                if scan_result.has_critical and self.config.security.secret_scan_fail_on_critical:
                    error_msg = (
                        f"Secret scan blocked assimilation: {scan_result.critical_count} "
                        f"critical finding(s) detected by {scan_result.scanner_used}"
                    )
                    result.error = error_msg
                    await self._update_discovery_status(
                        discovery.canonical_url, "blocked_secrets", error=error_msg
                    )
                    logger.warning(
                        "BLOCKED %s — %d critical secrets found",
                        discovery.canonical_url, scan_result.critical_count,
                    )
                    return result
                if scan_result.has_any:
                    logger.info(
                        "Secret scan for %s: %d non-critical finding(s), proceeding",
                        discovery.canonical_url, len(scan_result.findings),
                    )
                    if self.config.security.secret_scan_filter_in_serializer:
                        secret_scan_files = scan_result.file_paths_with_secrets

            # 1d. Detect license
            license_type = self._detect_license(clone_path)
            result.license_type = license_type
            logger.info("License detected for %s: %s", discovery.canonical_url, license_type)

            # Update status to 'mining'
            await self._update_discovery_status(discovery.canonical_url, "mining")

            # 2. Mine via existing RepoMiner
            repo_name = self._repo_name_from_url(discovery.canonical_url)
            mine_result: RepoMiningResult = await self.miner.mine_repo(
                repo_path=clone_path,
                repo_name=repo_name,
                target_project_id=target_project_id,
                metadata={"license_type": license_type},
                secret_scan_files=secret_scan_files,
            )

            if mine_result.error:
                result.error = mine_result.error
                await self._update_discovery_status(
                    discovery.canonical_url, "failed", error=mine_result.error
                )
                return result

            # 3. Record results
            result.success = True
            result.methodology_ids = mine_result.methodology_ids
            result.findings_count = len(mine_result.findings)
            result.head_sha = head_sha

            # 4. Update pulse_discoveries with results
            await self._update_discovery_assimilated(
                discovery.canonical_url,
                methodology_ids=mine_result.methodology_ids,
                mine_result_summary={
                    "findings": len(mine_result.findings),
                    "files_analyzed": mine_result.files_analyzed,
                    "tokens_used": mine_result.tokens_used,
                    "duration_seconds": round(mine_result.duration_seconds, 2),
                },
                license_type=license_type,
            )

            # 5. Populate freshness metadata
            try:
                pushed_at_str = ""
                # Get last commit date from git log
                proc = await asyncio.create_subprocess_exec(
                    "git", "log", "-1", "--format=%aI",
                    cwd=str(clone_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    pushed_at_str = stdout.decode().strip()

                await self._update_freshness_on_assimilate(
                    discovery.canonical_url, head_sha, pushed_at_str
                )
            except Exception as e:
                logger.warning(
                    "Failed to update freshness metadata for %s: %s",
                    discovery.canonical_url, e,
                )

            logger.info(
                "Assimilated %s: %d findings, %d methodologies",
                discovery.canonical_url,
                len(mine_result.findings),
                len(mine_result.methodology_ids),
            )

        except Exception as e:
            result.error = str(e)
            await self._update_discovery_status(
                discovery.canonical_url, "failed", error=str(e)
            )
            logger.error("Assimilation failed for %s: %s", discovery.canonical_url, e)

        finally:
            # 6. Cleanup clone
            if clone_path and clone_path.exists():
                await self._cleanup_clone(clone_path)

        return result

    async def _clone_repo(self, canonical_url: str) -> Path:
        """Shallow clone (--depth 1) to workspace directory."""
        self._workspace.mkdir(parents=True, exist_ok=True)

        repo_name = self._repo_name_from_url(canonical_url)
        clone_dir = self._workspace / f"{repo_name}_{uuid.uuid4().hex[:8]}"

        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", canonical_url, str(clone_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            raise RuntimeError(f"git clone failed: {error_msg}")

        logger.info("Cloned %s to %s", canonical_url, clone_dir)
        return clone_dir

    @staticmethod
    async def _get_head_sha(clone_path: Path) -> str:
        """Get HEAD SHA from a cloned repo."""
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            cwd=str(clone_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
        return ""

    async def _scan_for_secrets(self, path: Path) -> "ScanResult":
        """Run secret scanner on a cloned/mounted repo."""
        from claw.security.scanner import SecretScanner

        scanner = SecretScanner(
            timeout_seconds=self.config.security.secret_scan_timeout_seconds,
            no_verification=self.config.security.secret_scan_no_verification,
            fail_on_critical=self.config.security.secret_scan_fail_on_critical,
        )
        return await scanner.scan(path)

    @staticmethod
    def _detect_license(clone_path: Path) -> str:
        """Detect license from LICENSE/COPYING file in a cloned repo.

        Returns one of: permissive, copyleft, unknown, none.
        """
        license_filenames = [
            "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md",
            "COPYING", "COPYING.md", "LICENSE-MIT", "LICENSE-APACHE",
        ]
        license_text = ""
        for name in license_filenames:
            candidate = clone_path / name
            if candidate.is_file():
                try:
                    license_text = candidate.read_text(
                        encoding="utf-8", errors="replace"
                    )[:3000]
                    break
                except OSError:
                    continue

        if not license_text:
            return "none"

        header = "\n".join(license_text.splitlines()[:20]).lower()
        full_lower = license_text.lower()

        permissive_patterns = [
            "mit license",
            "permission is hereby granted, free of charge",
            "apache license",
            "licensed under the apache license, version 2.0",
            "bsd 2-clause",
            "bsd 3-clause",
            "redistribution and use in source and binary forms",
            "isc license",
            "the unlicense",
            "boost software license",
        ]
        copyleft_patterns = [
            "gnu general public license",
            "gnu affero general public license",
            "gnu lesser general public license",
            "mozilla public license",
            "gpl-2.0",
            "gpl-3.0",
            "agpl-3.0",
            "lgpl-",
        ]

        for pattern in permissive_patterns:
            if pattern in header or pattern in full_lower:
                return "permissive"
        for pattern in copyleft_patterns:
            if pattern in header or pattern in full_lower:
                return "copyleft"

        return "unknown"

    async def _update_freshness_on_assimilate(
        self, canonical_url: str, head_sha: str, pushed_at: str
    ) -> None:
        """Populate freshness metadata at assimilation time."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        await self.engine.execute(
            """UPDATE pulse_discoveries
               SET head_sha_at_mine = ?,
                   last_pushed_at = ?,
                   last_checked_at = ?,
                   freshness_status = 'fresh',
                   source_kind = CASE
                       WHEN canonical_url LIKE 'https://github.com/%' THEN 'github'
                       WHEN canonical_url LIKE 'https://huggingface.co/%' THEN 'hf_repo'
                       ELSE 'github'
                   END
               WHERE canonical_url = ?""",
            [head_sha, pushed_at, now, canonical_url],
        )

    async def _cleanup_clone(self, clone_path: Path) -> None:
        """Remove clone directory after mining."""
        try:
            shutil.rmtree(clone_path)
            logger.debug("Cleaned up clone: %s", clone_path)
        except Exception as e:
            logger.warning("Failed to clean up clone %s: %s", clone_path, e)

    async def _update_discovery_status(
        self,
        canonical_url: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Update the status of a pulse_discovery record."""
        if error:
            await self.engine.execute(
                "UPDATE pulse_discoveries SET status = ?, error_detail = ? WHERE canonical_url = ?",
                [status, error[:1000], canonical_url],
            )
        else:
            await self.engine.execute(
                "UPDATE pulse_discoveries SET status = ? WHERE canonical_url = ?",
                [status, canonical_url],
            )

    async def _update_discovery_assimilated(
        self,
        canonical_url: str,
        methodology_ids: list[str],
        mine_result_summary: dict,
        license_type: str = "",
    ) -> None:
        """Mark discovery as assimilated with mining results."""
        await self.engine.execute(
            """UPDATE pulse_discoveries
               SET status = 'assimilated',
                   methodology_ids = ?,
                   mine_result = ?,
                   license_type = ?
               WHERE canonical_url = ?""",
            [
                json.dumps(methodology_ids),
                json.dumps(mine_result_summary),
                license_type,
                canonical_url,
            ],
        )

    async def save_discovery(self, discovery: PulseDiscovery) -> None:
        """Persist a PulseDiscovery to the pulse_discoveries table."""
        disc_id = str(uuid.uuid4())
        await self.engine.execute(
            """INSERT OR IGNORE INTO pulse_discoveries
               (id, github_url, canonical_url, x_post_url, x_post_text,
                x_author_handle, novelty_score, scan_id, keywords_matched)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                disc_id,
                discovery.github_url,
                discovery.canonical_url,
                discovery.x_post_url,
                discovery.x_post_text[:500] if discovery.x_post_text else "",
                discovery.x_author_handle,
                discovery.novelty_score,
                discovery.scan_id,
                json.dumps(discovery.keywords_matched),
            ],
        )

    async def assimilate_hf_repo(
        self,
        repo_id: str,
        target_project_id: str,
        revision: str = "main",
    ) -> AssimilationResult:
        """Mount an HF repo via hf-mount adapter, mine it, then unmount.

        Args:
            repo_id: HuggingFace repo ID (e.g., "d4data/biomedical-ner-all").
            target_project_id: Project ID for storing findings.
            revision: Git revision to mount.

        Returns:
            AssimilationResult with success status and methodology IDs.
        """
        from claw.pulse.hf_adapter import HFMountAdapter, mining_strategy, classify_tier

        canonical_url = f"https://huggingface.co/{repo_id}"
        discovery = PulseDiscovery(
            github_url=canonical_url,
            canonical_url=canonical_url,
            x_post_text=f"HF repo ingest: {repo_id}",
            keywords_matched=["hf-ingest"],
            novelty_score=1.0,
            scan_id=f"hf-ingest-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
        )
        result = AssimilationResult(discovery=discovery)

        # Save discovery record
        await self.save_discovery(discovery)
        await self._update_discovery_status(canonical_url, "cloning")

        hf_cfg = self.config.pulse.hf_mount
        adapter = HFMountAdapter(
            mount_base=hf_cfg.mount_base,
            cache_size_bytes=hf_cfg.cache_size_bytes,
            cache_dir=hf_cfg.cache_dir,
            hf_token=os.getenv(hf_cfg.hf_token_env, ""),
            mount_timeout_secs=hf_cfg.mount_timeout_secs,
            fallback_to_download=hf_cfg.fallback_to_download,
        )

        mount_result = await adapter.mount_repo(repo_id, revision=revision)
        if not mount_result.success:
            result.error = f"Mount failed: {mount_result.error}"
            await self._update_discovery_status(canonical_url, "failed", error=result.error)
            return result

        mount_path = Path(mount_result.mount_path)
        try:
            # Pre-mine secret scan (Gate 1) for HF repos
            hf_secret_scan_files: set[str] | None = None
            if self.config.security.secret_scan_enabled:
                await self._update_discovery_status(canonical_url, "scanning")
                scan_result = await self._scan_for_secrets(mount_path)
                result.scan_result = scan_result
                if scan_result.has_critical and self.config.security.secret_scan_fail_on_critical:
                    error_msg = (
                        f"Secret scan blocked HF assimilation: {scan_result.critical_count} "
                        f"critical finding(s) detected by {scan_result.scanner_used}"
                    )
                    result.error = error_msg
                    await self._update_discovery_status(
                        canonical_url, "blocked_secrets", error=error_msg
                    )
                    logger.warning(
                        "BLOCKED %s — %d critical secrets found",
                        canonical_url, scan_result.critical_count,
                    )
                    return result
                if scan_result.has_any and self.config.security.secret_scan_filter_in_serializer:
                    hf_secret_scan_files = scan_result.file_paths_with_secrets

            await self._update_discovery_status(canonical_url, "mining")

            # Determine mining strategy based on tier
            tier = classify_tier(str(mount_path))
            strategy = mining_strategy(tier)
            if strategy["action"] == "skip":
                result.error = "Mount tier is PHANTOM — no files to mine"
                await self._update_discovery_status(canonical_url, "failed", error=result.error)
                return result

            # Use conservative max_bytes for mounted paths
            max_bytes = strategy.get("max_file_size", 500_000)

            # Mine using existing RepoMiner
            repo_name = repo_id.replace("/", "_")
            mine_result: RepoMiningResult = await self.miner.mine_repo(
                repo_path=mount_path,
                repo_name=repo_name,
                target_project_id=target_project_id,
                secret_scan_files=hf_secret_scan_files,
            )

            if mine_result.error:
                result.error = mine_result.error
                await self._update_discovery_status(canonical_url, "failed", error=mine_result.error)
                return result

            result.success = True
            result.methodology_ids = mine_result.methodology_ids
            result.findings_count = len(mine_result.findings)

            # Get HEAD SHA if possible
            head_sha = await self._get_head_sha(mount_path)
            result.head_sha = head_sha

            await self._update_discovery_assimilated(
                canonical_url,
                methodology_ids=mine_result.methodology_ids,
                mine_result_summary={
                    "findings": len(mine_result.findings),
                    "files_analyzed": mine_result.files_analyzed,
                    "tokens_used": mine_result.tokens_used,
                    "duration_seconds": round(mine_result.duration_seconds, 2),
                    "mount_method": mount_result.method,
                },
            )

            await self._update_freshness_on_assimilate(
                canonical_url, head_sha, ""
            )

            logger.info(
                "Assimilated HF repo %s via %s: %d findings, %d methodologies",
                repo_id, mount_result.method,
                len(mine_result.findings),
                len(mine_result.methodology_ids),
            )

        except Exception as e:
            result.error = str(e)
            await self._update_discovery_status(canonical_url, "failed", error=str(e))
            logger.error("HF assimilation failed for %s: %s", repo_id, e)

        finally:
            # Always unmount/cleanup
            await adapter.unmount(str(mount_path))

        return result

    @staticmethod
    def _repo_name_from_url(canonical_url: str) -> str:
        """Extract owner_repo name from canonical URL."""
        # https://github.com/owner/repo -> owner_repo
        # https://huggingface.co/owner/repo -> owner_repo
        path = canonical_url.replace("https://github.com/", "")
        path = path.replace("https://huggingface.co/", "")
        return path.replace("/", "_")
