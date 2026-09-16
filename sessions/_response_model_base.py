"""Compatibility base shared by the versioned API response models."""

import pydantic

if hasattr(pydantic.BaseModel, "model_validate"):

    class ContractModel(pydantic.BaseModel):
        """Reject undocumented response fields under Pydantic v2."""

        model_config = pydantic.ConfigDict(extra="forbid", populate_by_name=True)

else:  # pragma: no cover - exercised by deployments which still use Pydantic v1

    class ContractModel(pydantic.BaseModel):
        """Pydantic v1 equivalent of the strict response-model base."""

        class Config:
            extra = "forbid"
            allow_population_by_field_name = True
