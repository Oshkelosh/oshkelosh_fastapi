"""Pydantic configuration for the SSO tool addon."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, SecretStr, field_validator

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class GoogleProviderConfig(BaseModel):
    enabled: bool = False
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")


class FacebookProviderConfig(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret: SecretStr = SecretStr("")


class OidcProviderConfig(BaseModel):
    provider_id: str = "custom"
    display_name: str = "SSO"
    enabled: bool = False
    issuer_url: str = ""
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    scopes: str = "openid email profile"

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        slug = value.strip().lower().replace("-", "_")
        if not slug or not _SLUG_RE.match(slug):
            raise ValueError(
                "provider_id must start with a letter and contain only lowercase letters, digits, and underscores"
            )
        return slug


class SsoConfig(BaseModel):
    is_active: bool = True
    google: GoogleProviderConfig = Field(default_factory=GoogleProviderConfig)
    facebook: FacebookProviderConfig = Field(default_factory=FacebookProviderConfig)
    oidc_providers: list[OidcProviderConfig] = Field(default_factory=list)

    @classmethod
    def config_model(cls):
        return cls
