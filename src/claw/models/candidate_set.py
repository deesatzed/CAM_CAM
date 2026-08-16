"""Strict import of dated external model candidate selections."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from claw.models.catalog import ModelCatalog


class ImportedCandidateSet(BaseModel):
    """An OR_Checker selection validated against CAM's own model catalog."""

    model_config = ConfigDict(frozen=True)

    schema_version: int
    catalog_fetched_at_utc: datetime
    lookback_start_utc: datetime
    lookback_end_utc: datetime
    baseline_model: str = Field(min_length=1)
    selected_model_ids: tuple[str, ...] = Field(min_length=1)
    raw_catalog_digest: str = Field(alias="catalog_digest", pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _validate_shape(self) -> "ImportedCandidateSet":
        if self.schema_version != 1:
            raise ValueError("unsupported candidate-set schema version")
        if self.lookback_start_utc > self.lookback_end_utc:
            raise ValueError("candidate-set lookback window is inverted")
        if self.catalog_fetched_at_utc < self.lookback_end_utc:
            raise ValueError("catalog fetch predates candidate-set window")
        if self.selected_model_ids[0] != self.baseline_model:
            raise ValueError("candidate-set baseline must be first")
        if len(self.selected_model_ids) != len(set(self.selected_model_ids)):
            raise ValueError("candidate-set contains duplicate model IDs")
        return self

    @property
    def candidates(self) -> tuple[str, ...]:
        return self.selected_model_ids[1:]


def load_candidate_set(path: Path, *, catalog: ModelCatalog) -> ImportedCandidateSet:
    """Load an external selection and validate all IDs against CAM's snapshot.

    The artifact's raw OpenRouter digest is retained as provenance.  It is not
    compared with ``catalog.digest`` because CAM normalizes a different catalog
    representation before hashing it for benchmark authorization.
    """
    candidate_set = ImportedCandidateSet.model_validate_json(path.read_text())
    catalog.verify_digests()
    for model_id in candidate_set.selected_model_ids:
        entry = catalog.require(model_id)
        if entry.is_batch:
            raise ValueError(f"candidate-set contains batch model: {model_id}")
    return candidate_set
