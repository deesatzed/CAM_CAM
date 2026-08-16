"""Model discovery, benchmarking, and role-profile support for CAM."""

from claw.models.catalog import (
    ModelCatalog,
    ModelCatalogEntry,
    ModelPricing,
    OpenRouterCatalogClient,
)
from claw.models.candidate_set import ImportedCandidateSet, load_candidate_set

__all__ = [
    "ModelCatalog",
    "ModelCatalogEntry",
    "ModelPricing",
    "OpenRouterCatalogClient",
    "ImportedCandidateSet",
    "load_candidate_set",
]
