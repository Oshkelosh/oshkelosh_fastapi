"""Serialize addon config models for DB/registry storage."""

from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel, SecretStr


def _resolve_secrets(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, dict):
        return {key: _resolve_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_secrets(item) for item in value]
    return value


def dump_addon_config(model: BaseModel) -> dict[str, Any]:
    """Serialize addon config for persistence (preserves SecretStr values)."""
    return _resolve_secrets(model.model_dump())


def _is_secret_annotation(annotation: Any) -> bool:
    if annotation is SecretStr:
        return True
    origin = get_origin(annotation)
    if origin is None:
        return False
    return any(_is_secret_annotation(arg) for arg in get_args(annotation))


def iter_secret_field_paths(
    schema_model: type[BaseModel],
    *,
    prefix: tuple[str, ...] = (),
) -> list[tuple[str, ...]]:
    """Return dot-path tuples for every ``SecretStr`` field in a config schema."""
    paths: list[tuple[str, ...]] = []
    for name, field_info in schema_model.model_fields.items():
        path = (*prefix, name)
        annotation = field_info.annotation
        if _is_secret_annotation(annotation):
            paths.append(path)
            continue
        origin = get_origin(annotation)
        if origin is list:
            args = get_args(annotation)
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                paths.extend(iter_secret_field_paths(args[0], prefix=path))
            continue
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths.extend(iter_secret_field_paths(annotation, prefix=path))
    return paths


def get_config_at_path(config: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Read a nested value from a config dict using a path tuple."""
    current: Any = config
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def secret_fields_changed(
    before: dict[str, Any],
    after: dict[str, Any],
    paths: list[tuple[str, ...]],
) -> bool:
    """Return True when any secret path differs between two config dicts."""
    for path in paths:
        if get_config_at_path(before, path) != get_config_at_path(after, path):
            return True
    return False
