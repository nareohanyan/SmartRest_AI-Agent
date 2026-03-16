"""Shared schema base classes."""

from pydantic import BaseModel, ConfigDict


class SchemaModel(BaseModel):
    """Strict base for public schema contracts."""

    model_config = ConfigDict(extra="forbid")

