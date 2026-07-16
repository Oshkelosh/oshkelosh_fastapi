"""
Application configuration using Pydantic Settings.

Environment variables are loaded from a .env file if present,
and all settings are validated at startup.
"""

from pathlib import Path
from typing import Annotated, List, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DatabaseBackend = Literal["sqlite", "d1_http", "d1_binding"]
StorageBackend = Literal["local", "r2"]
DeploymentProfile = Literal["local", "cloudflare_remote", "cloudflare_workers"]

_PROFILE_BACKENDS: dict[DeploymentProfile, tuple[DatabaseBackend, StorageBackend]] = {
    "local": ("sqlite", "local"),
    "cloudflare_remote": ("d1_http", "r2"),
    "cloudflare_workers": ("d1_binding", "r2"),
}

_DEFAULT_JWT_SECRET = "change-me-in-production-use-a-strong-secret"
_MIN_JWT_SECRET_LEN = 32
LOCAL_MEDIA_MOUNT_PATH = "media/files"
SQLITE_DB_PATH = Path("data/oshkelosh.db")
LOCAL_MEDIA_DIR = Path("data/uploads")
APP_NAME = "Oshkelosh"


class Settings(BaseSettings):
    """Application settings backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------
    app_version: str = Field(
        default="0.1.0",
        description="Host application version (keep in sync with pyproject.toml)",
    )
    app_env: str = Field(default="development", description="Runtime environment")
    debug: bool = Field(default=False, description="Enable debug mode")

    # ------------------------------------------------------------------
    # Deployment backends
    # ------------------------------------------------------------------
    deployment_profile: Optional[DeploymentProfile] = Field(
        default=None,
        description="Preset mapping database + storage backends (overrides individual backends when set)",
    )
    database_backend: DatabaseBackend = Field(
        default="sqlite",
        description="Database backend: sqlite, d1_http, or d1_binding",
    )
    storage_backend: StorageBackend = Field(
        default="local",
        description="Object storage backend: local filesystem or r2",
    )

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    api_v1_prefix: str = Field(default="/api/v1", description="API version prefix")
    admin_prefix: str = Field(default="/admin", description="Admin panel prefix")

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://localhost:3000"],
        description="Comma-separated list of allowed CORS origins (string or JSON list)",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | List[str]) -> List[str]:
        """Parse the comma-separated origins string into a list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return list(value)

    @field_validator("trusted_proxy_ips", "trusted_proxy_headers", mode="before")
    @classmethod
    def parse_proxy_lists(cls, value: str | List[str]) -> List[str]:
        """Parse comma-separated proxy config lists."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)

    # ------------------------------------------------------------------
    # Cloudflare D1 (d1_http / d1_binding)
    # ------------------------------------------------------------------
    d1_account_id: Optional[str] = Field(
        default=None, description="Cloudflare account ID for D1"
    )
    d1_database_id: Optional[str] = Field(
        default=None, description="D1 database UUID"
    )
    d1_database_name: Optional[str] = Field(
        default=None, description="D1 database name (wrangler migrations)"
    )
    d1_api_token: Optional[str] = Field(
        default=None, description="Cloudflare API token with D1 write scope"
    )

    # ------------------------------------------------------------------
    # Product image processing
    # ------------------------------------------------------------------
    image_variant_full_max_px: int = Field(
        default=2000,
        description="Max longest edge in pixels for full product images",
    )
    image_variant_card_max_px: int = Field(
        default=800,
        description="Max longest edge in pixels for storefront card images",
    )
    image_variant_thumb_max_px: int = Field(
        default=256,
        description="Max longest edge in pixels for admin list thumbnails",
    )

    # ------------------------------------------------------------------
    # Cloudflare R2 (storage_backend=r2)
    # ------------------------------------------------------------------
    r2_account_id: Optional[str] = Field(
        default=None, description="Cloudflare account ID for R2"
    )
    r2_access_key_id: Optional[str] = Field(
        default=None, description="R2 S3 API access key ID"
    )
    r2_secret_access_key: Optional[str] = Field(
        default=None, description="R2 S3 API secret access key"
    )
    r2_bucket_name: Optional[str] = Field(
        default=None, description="R2 bucket name for file uploads"
    )
    r2_public_base_url: Optional[str] = Field(
        default=None,
        description="Optional public CDN/base URL for R2 objects (defaults to r2.dev pub URL)",
    )

    # Legacy combined token (access_key:secret) — still accepted for migration
    r2_api_token: Optional[str] = Field(
        default=None,
        description="Deprecated: use R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY",
    )

    # ------------------------------------------------------------------
    # JWT / Authentication
    # ------------------------------------------------------------------
    jwt_secret_key: str = Field(
        default=_DEFAULT_JWT_SECRET,
        description="Secret key for JWT signing (HS256)",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_access_token_expire_minutes: int = Field(
        default=30, description="Access token lifetime in minutes"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7, description="Refresh token lifetime in days"
    )
    jwt_refresh_secret_key: Optional[str] = Field(
        default=None,
        description="Separate secret for refresh tokens (defaults to jwt_secret_key)",
    )
    public_app_url: Optional[str] = Field(
        default=None,
        description="Canonical public storefront URL (links, local media URLs, auth emails)",
    )
    require_email_verification: bool = Field(
        default=True,
        description=(
            "When true, send a verification email after registration. "
            "Verification is optional and never blocks login or API access."
        ),
    )
    email_verification_expire_hours: int = Field(
        default=24,
        description="Hours until an email verification link expires",
    )
    password_reset_expire_hours: int = Field(
        default=1,
        description="Hours until a password reset link expires",
    )
    admin_session_secret: Optional[str] = Field(
        default=None,
        description="Secret for admin session cookies (defaults to jwt_secret_key in dev only)",
    )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable API rate limiting on auth endpoints",
    )
    rate_limit_login: str = Field(
        default="5/minute",
        description="slowapi limit string for POST /auth/login",
    )
    rate_limit_register: str = Field(
        default="3/hour",
        description="slowapi limit string for POST /auth/register",
    )
    rate_limit_refresh: str = Field(
        default="10/minute",
        description="slowapi limit string for POST /auth/refresh",
    )
    rate_limit_admin_login: str = Field(
        default="5/minute",
        description="slowapi limit string for POST /admin/login",
    )
    trusted_proxy_ips: Annotated[List[str], NoDecode] = Field(
        default_factory=list,
        description="Comma-separated proxy IP allowlist for trusting forwarded client IP headers",
    )
    trusted_proxy_headers: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["x-forwarded-for", "x-real-ip"],
        description="Comma-separated header names checked for forwarded client IPs",
    )
    admin_cookie_samesite: Literal["lax", "strict"] = Field(
        default="lax",
        description="SameSite attribute for admin session cookies (lax or strict)",
    )
    pending_order_expiry_hours: int = Field(
        default=48,
        ge=1,
        le=720,
        description="Auto-cancel pending orders older than this many hours",
    )
    order_idempotency_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Hours to honor Idempotency-Key replays for POST /orders",
    )
    flash_cookie_max_age: int = Field(
        default=60,
        ge=5,
        le=3600,
        description="Max age in seconds for admin flash message cookies",
    )

    # ------------------------------------------------------------------
    # Password hashing
    # ------------------------------------------------------------------
    bcrypt_rounds: int = Field(
        default=12,
        ge=10,
        le=15,
        description="bcrypt cost factor for password hashing",
    )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = Field(default="INFO", description="Loguru log level")

    # ------------------------------------------------------------------
    # Addon install (admin dashboard)
    # ------------------------------------------------------------------
    addon_install_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1024,
        description="Maximum addon ZIP size in bytes",
    )
    addon_install_allowed_hosts: Annotated[List[str], NoDecode] = Field(
        default_factory=list,
        description="Comma-separated HTTPS host allowlist for URL installs (empty = any public HTTPS host)",
    )
    addon_install_restart_flag_file: Optional[str] = Field(
        default="data/restart.flag",
        description="Write a restart flag here after successful addon install (empty = disabled)",
    )
    addon_install_restart_flag_format: Literal["json", "text"] = Field(
        default="json",
        description="Payload format for the restart flag file",
    )
    host_self_update_enabled: bool = Field(
        default=False,
        description="Allow Admin Dashboard to git-pull and restart this host install",
    )
    host_repo_root: Optional[str] = Field(
        default=None,
        description="Git working tree for host self-update (empty = current working directory)",
    )

    @field_validator("addon_install_allowed_hosts", mode="before")
    @classmethod
    def parse_addon_install_allowed_hosts(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, str):
            if not value.strip():
                return []
            return [host.strip().lower() for host in value.split(",") if host.strip()]
        return [host.lower() for host in value]

    @property
    def addon_install_restart_flag_path(self) -> Optional[Path]:
        if not self.addon_install_restart_flag_file or not self.addon_install_restart_flag_file.strip():
            return None
        return Path(self.addon_install_restart_flag_file)

    @property
    def host_repo_root_path(self) -> Path:
        if self.host_repo_root and self.host_repo_root.strip():
            return Path(self.host_repo_root).resolve()
        return Path.cwd().resolve()

    @model_validator(mode="after")
    def apply_deployment_profile(self) -> "Settings":
        """Map deployment_profile preset to database and storage backends."""
        if self.deployment_profile is not None:
            db, storage = _PROFILE_BACKENDS[self.deployment_profile]
            object.__setattr__(self, "database_backend", db)
            object.__setattr__(self, "storage_backend", storage)
        return self

    @model_validator(mode="after")
    def migrate_r2_api_token(self) -> "Settings":
        """Split legacy r2_api_token into access key + secret when needed."""
        if self.r2_api_token and ":" in self.r2_api_token:
            parts = self.r2_api_token.split(":", 1)
            if not self.r2_access_key_id:
                object.__setattr__(self, "r2_access_key_id", parts[0])
            if not self.r2_secret_access_key:
                object.__setattr__(self, "r2_secret_access_key", parts[1])
        elif self.r2_api_token and not self.r2_access_key_id:
            object.__setattr__(self, "r2_access_key_id", self.r2_api_token)
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def has_d1_http(self) -> bool:
        return self.database_backend == "d1_http"

    @property
    def has_r2_storage(self) -> bool:
        return self.storage_backend == "r2"

    @property
    def has_local_storage(self) -> bool:
        return self.storage_backend == "local"

    @property
    def refresh_secret(self) -> str:
        return self.jwt_refresh_secret_key or self.jwt_secret_key

    @property
    def session_secret(self) -> str:
        """Secret for admin session JWT cookies."""
        return self.admin_session_secret or self.jwt_secret_key

    @property
    def app_name(self) -> str:
        """Fixed application name."""
        return APP_NAME

    @property
    def d1_local_db_path(self) -> str:
        """Fixed SQLite database path (database_backend=sqlite)."""
        return str(SQLITE_DB_PATH)

    @property
    def local_media_path(self) -> Path:
        """Fixed local media upload directory (storage_backend=local)."""
        return LOCAL_MEDIA_DIR

    def public_app_origin(self) -> str:
        """Resolve the public app origin used for absolute storefront and media URLs."""
        if self.public_app_url and self.public_app_url.strip():
            return self.public_app_url.strip().rstrip("/")
        if self.cors_origins:
            return self.cors_origins[0].rstrip("/")
        return "http://localhost:8000"

    @property
    def local_media_base_url(self) -> str:
        """Public base URL for locally stored media (derived from PUBLIC_APP_URL)."""
        return f"{self.public_app_origin()}/{LOCAL_MEDIA_MOUNT_PATH}"


def validate_backends(cfg: Settings) -> None:
    """Fail fast when required credentials or paths are missing for chosen backends."""
    errors: list[str] = []

    if cfg.app_env == "production":
        if cfg.jwt_secret_key == _DEFAULT_JWT_SECRET:
            errors.append(
                "JWT_SECRET_KEY must be set to a strong secret in production "
                f"(not the default placeholder)"
            )
        elif len(cfg.jwt_secret_key) < _MIN_JWT_SECRET_LEN:
            errors.append(
                f"JWT_SECRET_KEY must be at least {_MIN_JWT_SECRET_LEN} characters in production"
            )
        if not cfg.admin_session_secret:
            errors.append(
                "ADMIN_SESSION_SECRET must be set in production (separate from JWT_SECRET_KEY)"
            )
        elif cfg.admin_session_secret == cfg.jwt_secret_key:
            errors.append(
                "ADMIN_SESSION_SECRET must differ from JWT_SECRET_KEY in production"
            )
        elif len(cfg.admin_session_secret) < _MIN_JWT_SECRET_LEN:
            errors.append(
                f"ADMIN_SESSION_SECRET must be at least {_MIN_JWT_SECRET_LEN} characters in production"
            )

    if cfg.database_backend == "sqlite":
        parent = SQLITE_DB_PATH.parent
        if parent != Path(".") and not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"Cannot create SQLite directory {parent}: {exc}")

    elif cfg.database_backend == "d1_http":
        if not cfg.d1_account_id:
            errors.append("D1_ACCOUNT_ID is required for database_backend=d1_http")
        if not cfg.d1_database_id:
            errors.append("D1_DATABASE_ID is required for database_backend=d1_http")
        if not cfg.d1_api_token:
            errors.append("D1_API_TOKEN is required for database_backend=d1_http")

    elif cfg.database_backend == "d1_binding":
        from app.db.backends.d1_binding import D1BindingNotConfiguredError, get_d1_binding

        if cfg.app_env == "production":
            try:
                get_d1_binding()
            except D1BindingNotConfiguredError:
                errors.append(
                    "database_backend=d1_binding requires set_d1_binding() from the Worker entrypoint"
                )

    if cfg.storage_backend == "local":
        media_dir = LOCAL_MEDIA_DIR
        try:
            media_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            errors.append(f"Cannot create local media directory {media_dir}: {exc}")

    elif cfg.storage_backend == "r2":
        if not cfg.r2_account_id:
            errors.append("R2_ACCOUNT_ID is required for storage_backend=r2")
        if not cfg.r2_access_key_id:
            errors.append("R2_ACCESS_KEY_ID is required for storage_backend=r2")
        if not cfg.r2_secret_access_key:
            errors.append("R2_SECRET_ACCESS_KEY is required for storage_backend=r2")
        if not cfg.r2_bucket_name:
            errors.append("R2_BUCKET_NAME is required for storage_backend=r2")

    if errors:
        raise ValueError("Backend configuration invalid:\n  - " + "\n  - ".join(errors))


# ------------------------------------------------------------------
# Singleton instance (lazy-loaded)
# ------------------------------------------------------------------
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Clear cached settings (useful in tests)."""
    global _settings, settings
    _settings = None
    settings = get_settings()
    return settings


settings = get_settings()
