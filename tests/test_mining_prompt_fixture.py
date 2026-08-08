from __future__ import annotations

import hashlib
import os
from pathlib import Path

from claw.core.config import ClawConfig
from claw.miner import RepoMiner


class ReadOnlyRepository:
    def __init__(self) -> None:
        self.reads = 0

    async def get_methodologies_by_tag(self, _tag: str, limit: int = 50) -> list:
        self.reads += 1
        assert limit == 50
        return []

    def __getattr__(self, name: str):
        raise AssertionError(f"Unexpected repository access: {name}")


def _write_fixture_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# Fixture\n\nA tested retry and queue library.\n")
    (path / "retry.py").write_text(
        "def retry(operation, attempts=3):\n"
        "    for attempt in range(attempts):\n"
        "        try:\n"
        "            return operation()\n"
        "        except Exception:\n"
        "            if attempt == attempts - 1:\n"
        "                raise\n"
        + "# deterministic padding\n" * 80
    )
    (path / "queue.py").write_text(
        "class DurableQueue:\n"
        "    def put(self, item):\n"
        "        return {'queued': item}\n"
        + "# queue padding\n" * 80
    )


async def test_prepare_mining_prompt_is_stable_and_read_only(tmp_path: Path) -> None:
    repo_path = tmp_path / "fixture-repo"
    _write_fixture_repo(repo_path)
    repository = ReadOnlyRepository()
    miner = RepoMiner(
        repository=repository,
        llm_client=None,
        semantic_memory=None,
        config=ClawConfig(),
        scan_ledger_path=tmp_path / "ledger.json",
    )

    first = await miner.prepare_mining_prompt(repo_path, "fixture-repo", "python", set())
    for source_path in repo_path.iterdir():
        os.utime(source_path, (source_path.stat().st_atime, source_path.stat().st_mtime + 60))
    second = await miner.prepare_mining_prompt(repo_path, "fixture-repo", "python", set())

    assert first.prompt_sha256 == hashlib.sha256(first.prompt.encode()).hexdigest()
    assert first.prompt_sha256 == second.prompt_sha256
    assert first.repo_content_sha256 == second.repo_content_sha256
    assert first.source_manifest == ["README.md", "queue.py", "retry.py"]
    assert first.file_count == 3
    assert first.repo_bytes > 1024
    assert '"findings": [' in first.prompt
    assert "Maximum 5 findings per repo" in first.prompt
    assert "aim for at least 3" in first.prompt
    assert repository.reads == 2
    assert not (tmp_path / "ledger.json").exists()


async def test_prepare_mining_prompt_changes_after_source_change(tmp_path: Path) -> None:
    repo_path = tmp_path / "fixture-repo"
    _write_fixture_repo(repo_path)
    miner = RepoMiner(
        repository=ReadOnlyRepository(),
        llm_client=None,
        semantic_memory=None,
        config=ClawConfig(),
        scan_ledger_path=tmp_path / "ledger.json",
    )

    before = await miner.prepare_mining_prompt(repo_path, "fixture-repo", "python", set())
    retry_path = repo_path / "retry.py"
    retry_path.write_text(retry_path.read_text() + "\nRETRY_LIMIT = 5\n")
    after = await miner.prepare_mining_prompt(repo_path, "fixture-repo", "python", set())

    assert after.repo_content_sha256 != before.repo_content_sha256
    assert after.prompt_sha256 != before.prompt_sha256
