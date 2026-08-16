from __future__ import annotations

import json
from pathlib import Path

import pytest

from claw.models.candidate_set import load_candidate_set
from claw.models.catalog import ModelCatalog


def _catalog() -> ModelCatalog:
    payload = json.loads((Path(__file__).parent / "fixtures" / "openrouter_models.json").read_text())
    return ModelCatalog.from_payload(payload)


def _artifact(*, selected: list[str] | None = None, raw_digest: str = "a" * 64) -> dict:
    ids = selected or ["z-ai/glm-5.2", "openai/gpt-5.6-luna"]
    return {
        "schema_version": 1,
        "catalog_fetched_at_utc": "2026-08-16T00:00:00Z",
        "lookback_start_utc": "2026-07-17T00:00:00Z",
        "lookback_end_utc": "2026-08-16T00:00:00Z",
        "baseline_model": "z-ai/glm-5.2",
        "selected_model_ids": ids,
        "catalog_digest": raw_digest,
    }


def _write(tmp_path: Path, artifact: dict) -> Path:
    path = tmp_path / "candidate-set.json"
    path.write_text(json.dumps(artifact))
    return path


def test_import_retains_raw_catalog_provenance_and_validates_candidate_ids(tmp_path: Path) -> None:
    imported = load_candidate_set(_write(tmp_path, _artifact()), catalog=_catalog())

    assert imported.raw_catalog_digest == "a" * 64
    assert imported.baseline_model == "z-ai/glm-5.2"
    assert imported.candidates == ("openai/gpt-5.6-luna",)


@pytest.mark.parametrize(
    "artifact, message",
    [
        (_artifact(selected=["z-ai/glm-5.2", "not/a-model"]), "not found"),
        (_artifact(selected=["z-ai/glm-5.2", "google/gemini-3.6-flash:batch"]), "batch"),
        (_artifact(selected=["z-ai/glm-5.2", "z-ai/glm-5.2"]), "duplicate"),
        (_artifact(selected=["openai/gpt-5.6-luna", "z-ai/glm-5.2"]), "baseline"),
        (_artifact(raw_digest="not-a-digest"), "digest"),
    ],
)
def test_import_rejects_invalid_or_unusable_candidate_sets(
    tmp_path: Path,
    artifact: dict,
    message: str,
) -> None:
    with pytest.raises((KeyError, ValueError), match=message):
        load_candidate_set(_write(tmp_path, artifact), catalog=_catalog())


def test_import_rejects_inverted_time_window(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["lookback_start_utc"] = "2026-08-17T00:00:00Z"

    with pytest.raises(ValueError, match="window"):
        load_candidate_set(_write(tmp_path, artifact), catalog=_catalog())
