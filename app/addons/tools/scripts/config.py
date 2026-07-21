"""Pydantic configuration for the Scripts tool addon."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.addons.tools.scripts.parse import require_https_src


class ScriptEntry(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    routes: Literal["all", "public", "private"] = "all"
    src: str = Field(min_length=8, max_length=2048)
    attrs: dict[str, str | bool] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name is required")
        return name

    @field_validator("src")
    @classmethod
    def validate_src(cls, value: str) -> str:
        return require_https_src(value.strip())

    @field_validator("attrs")
    @classmethod
    def validate_attrs(cls, value: dict[str, Any]) -> dict[str, str | bool]:
        cleaned: dict[str, str | bool] = {}
        for key, raw in value.items():
            name = str(key).lower().strip()
            if not name or name == "src" or name.startswith("on"):
                raise ValueError(f"Invalid attribute: {key}")
            if isinstance(raw, bool):
                cleaned[name] = raw
            else:
                cleaned[name] = str(raw)
        return cleaned


class ScriptsConfig(BaseModel):
    scripts: list[ScriptEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> ScriptsConfig:
        ids = [entry.id for entry in self.scripts]
        if len(ids) != len(set(ids)):
            raise ValueError("script ids must be unique")
        return self

    @classmethod
    def config_model(cls):
        return cls
