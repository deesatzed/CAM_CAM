"""Tests for SHA capture and freshness metadata wiring in assimilator.py.

Track A: Validates _get_head_sha(), _update_freshness_on_assimilate(),
and _repo_name_from_url() HF support. Uses real git repos and real SQLite.

NO MOCKS. All git operations use real temporary repositories.
All DB operations use real in-memory SQLite.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from claw.core.config import DatabaseConfig, load_config
from claw.db.engine import DatabaseEngine
from claw.pulse.assimilator import PulseAssimilator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def pulse_engine():
    """Real SQLite in-memory engine with full schema for freshness columns."""
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


@pytest.fixture
async def assimilator(pulse_engine):
    """PulseAssimilator with real engine and real RepoMiner dependencies."""
    from claw.db.embeddings import EmbeddingEngine
    from claw.db.repository import Repository
    from claw.llm.client import LLMClient
    from claw.memory.hybrid_search import HybridSearch
    from claw.memory.semantic import SemanticMemory
    from claw.miner import RepoMiner

    config = load_config()
    repository = Repository(pulse_engine)
    embedding_engine = EmbeddingEngine()
    hybrid_search = HybridSearch(repository, embedding_engine)
    llm_client = LLMClient(config.llm)
    semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)
    miner = RepoMiner(repository, llm_client, semantic_memory, config)
    return PulseAssimilator(pulse_engine, miner, config)


# ---------------------------------------------------------------------------
# TestGetHeadSha
# ---------------------------------------------------------------------------

def _init_repo_with_identity(path: str) -> None:
    subprocess.run(["git", "init", path], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", path, "config", "user.email", "ci@example.invalid"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", path, "config", "user.name", "CAM CI"],
        capture_output=True,
        check=True,
    )


class TestGetHeadSha:
    """Tests for PulseAssimilator._get_head_sha() using real git repos."""

    async def test_get_head_sha_real_git_repo(self):
        """Create a real temp git repo, verify _get_head_sha returns 40-char hex."""
        with tempfile.TemporaryDirectory() as td:
            _init_repo_with_identity(td)
            subprocess.run(
                ["git", "-C", td, "commit", "--allow-empty", "-m", "init"],
                capture_output=True, check=True,
            )
            sha = await PulseAssimilator._get_head_sha(Path(td))
            assert len(sha) == 40
            assert all(c in "0123456789abcdef" for c in sha)

    async def test_get_head_sha_no_git(self):
        """Non-git directory returns empty string, not an error."""
        with tempfile.TemporaryDirectory() as td:
            sha = await PulseAssimilator._get_head_sha(Path(td))
            assert sha == ""

    async def test_get_head_sha_matches_subprocess(self):
        """SHA returned by _get_head_sha matches direct subprocess call."""
        with tempfile.TemporaryDirectory() as td:
            _init_repo_with_identity(td)
            subprocess.run(
                ["git", "-C", td, "commit", "--allow-empty", "-m", "test"],
                capture_output=True, check=True,
            )
            expected = subprocess.run(
                ["git", "-C", td, "rev-parse", "HEAD"],
                capture_output=True, text=True,
            ).stdout.strip()
            actual = await PulseAssimilator._get_head_sha(Path(td))
            assert actual == expected

    async def test_get_head_sha_changes_after_new_commit(self):
        """A new commit produces a different SHA."""
        with tempfile.TemporaryDirectory() as td:
            _init_repo_with_identity(td)
            subprocess.run(
                ["git", "-C", td, "commit", "--allow-empty", "-m", "first"],
                capture_output=True, check=True,
            )
            sha1 = await PulseAssimilator._get_head_sha(Path(td))

            subprocess.run(
                ["git", "-C", td, "commit", "--allow-empty", "-m", "second"],
                capture_output=True, check=True,
            )
            sha2 = await PulseAssimilator._get_head_sha(Path(td))

            assert sha1 != sha2
            assert len(sha2) == 40

    async def test_get_head_sha_empty_repo_no_commits(self):
        """A git init with no commits returns empty string (no HEAD yet)."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True, check=True)
            sha = await PulseAssimilator._get_head_sha(Path(td))
            assert sha == ""


# ---------------------------------------------------------------------------
# TestUpdateFreshnessOnAssimilate
# ---------------------------------------------------------------------------

class TestUpdateFreshnessOnAssimilate:
    """Tests for _update_freshness_on_assimilate() SQL UPDATE logic."""

    async def test_updates_freshness_columns_github(self, assimilator, pulse_engine):
        """Freshness metadata written correctly for a GitHub URL."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('d1', 'https://github.com/test/repo',
                        'https://github.com/test/repo', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://github.com/test/repo",
            "abc123def456789012345678901234567890abcd",
            "2026-03-25T10:00:00+00:00",
        )

        row = await pulse_engine.fetch_one(
            """SELECT head_sha_at_mine, last_pushed_at, freshness_status,
                      source_kind, last_checked_at
               FROM pulse_discoveries WHERE canonical_url = ?""",
            ["https://github.com/test/repo"],
        )
        assert row is not None
        assert row["head_sha_at_mine"] == "abc123def456789012345678901234567890abcd"
        assert row["last_pushed_at"] == "2026-03-25T10:00:00+00:00"
        assert row["freshness_status"] == "fresh"
        assert row["source_kind"] == "github"
        assert row["last_checked_at"] is not None  # Timestamp was set

    async def test_updates_freshness_columns_hf(self, assimilator, pulse_engine):
        """source_kind auto-detected as 'hf_repo' for Hugging Face URLs."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('d2', 'https://huggingface.co/test/model',
                        'https://huggingface.co/test/model', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://huggingface.co/test/model",
            "sha256abc",
            "2026-03-25T12:00:00+00:00",
        )

        row = await pulse_engine.fetch_one(
            "SELECT source_kind, freshness_status FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/model"],
        )
        assert row is not None
        assert row["source_kind"] == "hf_repo"
        assert row["freshness_status"] == "fresh"

    async def test_updates_unknown_url_defaults_to_github(self, assimilator, pulse_engine):
        """A non-GitHub, non-HF URL defaults source_kind to 'github'."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('d3', 'https://gitlab.com/test/repo',
                        'https://gitlab.com/test/repo', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://gitlab.com/test/repo", "somesha", ""
        )

        row = await pulse_engine.fetch_one(
            "SELECT source_kind FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://gitlab.com/test/repo"],
        )
        assert row is not None
        assert row["source_kind"] == "github"  # Default ELSE clause

    async def test_no_op_for_missing_row(self, assimilator, pulse_engine):
        """Updating a non-existent canonical_url does not raise."""
        # Should execute without error even though no row matches
        await assimilator._update_freshness_on_assimilate(
            "https://github.com/nonexistent/repo", "sha123", "2026-01-01T00:00:00Z"
        )
        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/nonexistent/repo"],
        )
        assert row["cnt"] == 0

    async def test_overwrites_previous_freshness(self, assimilator, pulse_engine):
        """Calling _update_freshness_on_assimilate twice overwrites the first values."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('d4', 'https://github.com/test/overwrite',
                        'https://github.com/test/overwrite', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://github.com/test/overwrite", "sha_first", "2026-01-01T00:00:00Z"
        )
        await assimilator._update_freshness_on_assimilate(
            "https://github.com/test/overwrite", "sha_second", "2026-06-01T00:00:00Z"
        )

        row = await pulse_engine.fetch_one(
            "SELECT head_sha_at_mine, last_pushed_at FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/test/overwrite"],
        )
        assert row["head_sha_at_mine"] == "sha_second"
        assert row["last_pushed_at"] == "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# TestRepoNameFromUrl
# ---------------------------------------------------------------------------

class TestRepoNameFromUrl:
    """Tests for _repo_name_from_url() including HF URL support."""

    def test_github_url(self):
        result = PulseAssimilator._repo_name_from_url("https://github.com/owner/repo")
        assert result == "owner_repo"

    def test_github_url_with_subpath(self):
        result = PulseAssimilator._repo_name_from_url("https://github.com/org/my-project")
        assert result == "org_my-project"

    def test_hf_url(self):
        result = PulseAssimilator._repo_name_from_url("https://huggingface.co/owner/model")
        assert result == "owner_model"

    def test_hf_url_nested(self):
        result = PulseAssimilator._repo_name_from_url("https://huggingface.co/bigscience/bloom")
        assert result == "bigscience_bloom"

    def test_unknown_url_passthrough(self):
        """Non-GitHub/HF URLs get slashes replaced but prefix kept."""
        result = PulseAssimilator._repo_name_from_url("https://gitlab.com/org/repo")
        # The method only strips known prefixes; gitlab URL stays intact after replacements
        assert "_" in result

    def test_github_url_with_trailing_segments(self):
        """Extra path segments (like /tree/main) get included in the name."""
        result = PulseAssimilator._repo_name_from_url("https://github.com/owner/repo/tree/main")
        assert result.startswith("owner_repo")


# ---------------------------------------------------------------------------
# TestSeedExistingRepos
# ---------------------------------------------------------------------------

class TestSeedExistingRepos:
    """Tests for FreshnessMonitor.seed_existing_repos() database logic."""

    async def test_seed_empty_db_returns_zero(self, pulse_engine):
        """Empty database has nothing to seed."""
        from claw.pulse.freshness import FreshnessMonitor
        config = load_config()
        monitor = FreshnessMonitor(pulse_engine, config)
        result = await monitor.seed_existing_repos()
        assert result == 0

    async def test_seed_skips_already_seeded(self, pulse_engine):
        """Repos with existing head_sha_at_mine are not re-seeded."""
        from claw.pulse.freshness import FreshnessMonitor

        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status, head_sha_at_mine, source_kind)
               VALUES ('d1', 'https://github.com/test/repo',
                        'https://github.com/test/repo', 'assimilated', 'abc123', 'github')"""
        )

        config = load_config()
        monitor = FreshnessMonitor(pulse_engine, config)
        result = await monitor.seed_existing_repos()
        assert result == 0  # Already has head_sha, should skip

    async def test_seed_skips_non_assimilated(self, pulse_engine):
        """Only 'assimilated' status repos are eligible for seeding."""
        from claw.pulse.freshness import FreshnessMonitor

        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status)
               VALUES ('d2', 'https://github.com/test/pending',
                        'https://github.com/test/pending', 'discovered')"""
        )

        config = load_config()
        monitor = FreshnessMonitor(pulse_engine, config)
        result = await monitor.seed_existing_repos()
        assert result == 0  # Status is 'discovered', not 'assimilated'
