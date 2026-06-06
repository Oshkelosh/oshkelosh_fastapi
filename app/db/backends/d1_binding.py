"""Cloudflare Workers D1 binding backend (stub).

When running on Cloudflare Workers with Python, inject the D1 binding from
``env.DB`` into ``set_d1_binding()`` before handling requests.
"""


class D1BindingNotConfiguredError(RuntimeError):
    """Raised when d1_binding backend is selected but no Worker binding is set."""

    def __init__(self) -> None:
        super().__init__(
            "database_backend=d1_binding requires a Cloudflare Workers D1 binding. "
            "Use deployment_profile=cloudflare_remote for HTTP API access from "
            "Docker/VPS, or deployment_profile=local for SQLite development."
        )


_binding: object | None = None


def set_d1_binding(binding: object) -> None:
    """Register the Workers ``env.DB`` binding (called from Worker entrypoint)."""
    global _binding
    _binding = binding


def get_d1_binding() -> object:
    """Return the registered D1 binding or raise."""
    if _binding is None:
        raise D1BindingNotConfiguredError()
    return _binding


def clear_d1_binding() -> None:
    """Clear binding (tests)."""
    global _binding
    _binding = None
