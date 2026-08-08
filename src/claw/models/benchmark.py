"""Frozen inputs and evidence types for CAM mining-model benchmarks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MiningPromptFixture(BaseModel):
    """Exact, content-addressed prompt emitted by the production miner."""

    model_config = ConfigDict(frozen=True)

    repo_path: str
    repo_name: str
    git_head: str | None = None
    dirty_paths: list[str] = Field(default_factory=list)
    brain: str
    prompt: str
    prompt_sha256: str
    repo_content: str
    repo_content_sha256: str
    source_manifest: list[str]
    repo_bytes: int
    file_count: int
    estimated_tokens: int
    token_budget: int
    domain_info: dict
    overlap: dict
