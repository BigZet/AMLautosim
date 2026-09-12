"""Presentation metadata for independent configuration editors."""

from pydantic import BaseModel


class NumericOverrideOut(BaseModel):
    key: str
    label: str
    integer: bool
    minimum: str | None = None
    maximum: str | None = None
    exclusive_minimum: bool = False
    decimal_places: int | None = None


class EditorMetadataOut(BaseModel):
    version: int
    schema_version: int
    limits: dict[str, int]
    labels: dict[str, str]
    quotas: dict[str, str]
    resource_weights: dict[str, str]
    supported_versions: dict[str, list[str]]
    dictionary_keys: dict[str, list[str]]
    overrides: list[NumericOverrideOut]
