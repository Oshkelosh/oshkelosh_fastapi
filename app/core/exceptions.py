"""
Custom exception classes for the Oshkelosh framework.

Each exception carries a human-readable message, an HTTP status code,
and an optional error code that clients can use for programmatic handling.
"""

from http import HTTPStatus
from typing import Any, Optional


class AppException(Exception):
    """Base exception for all application-level errors."""

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR,
        error_code: Optional[str] = None,
        details: Optional[Any] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or "internal_error"
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error": self.error_code,
            "message": self.message,
        }
        if self.details is not None:
            result["details"] = self.details
        return result


class NotFound(AppException):
    """Resource was not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        resource_name: str = "",
        resource_id: Optional[str] = None,
        details: Optional[Any] = None,
    ):
        if resource_name or resource_id:
            parts = []
            if resource_name:
                parts.append(resource_name)
            if resource_id:
                parts.append(str(resource_id))
            if parts:
                message = f"{' '.join(parts)} not found"
        super().__init__(
            message=message,
            status_code=HTTPStatus.NOT_FOUND,
            error_code="not_found",
            details=details,
        )


class ValidationError(AppException):
    """Input validation failed."""

    def __init__(
        self,
        message: str = "Validation error",
        errors: Optional[dict[str, Any]] = None,
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="validation_error",
            details=errors if errors is not None else details,
        )


class AuthenticationError(AppException):
    """Authentication failed or credentials are missing/invalid."""

    def __init__(
        self,
        message: str = "Authentication required",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTPStatus.UNAUTHORIZED,
            error_code="authentication_required",
            details=details,
        )


class AuthorizationError(AppException):
    """User lacks permission for the requested action."""

    def __init__(
        self,
        message: str = "Insufficient permissions",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTPStatus.FORBIDDEN,
            error_code="forbidden",
            details=details,
        )


class RateLimitExceeded(AppException):
    """Rate limit threshold has been exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            error_code="rate_limit_exceeded",
            details=details,
        )
        self.retry_after = retry_after  # seconds

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.retry_after is not None:
            result["retry_after"] = self.retry_after
        return result
