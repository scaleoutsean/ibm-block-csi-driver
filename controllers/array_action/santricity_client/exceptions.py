"""Custom exception hierarchy for the SANtricity client."""

from __future__ import annotations

from typing import Any


class SANtricityError(RuntimeError):
    """Base error for SANtricity failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class AuthenticationError(SANtricityError):
    """Raised when credentials fail or tokens expire."""


class RequestError(SANtricityError):
    """Raised when an HTTP request cannot be fulfilled."""


class UnexpectedResponseError(SANtricityError):
    """Raised when the API returns an unexpected payload structure."""


class ResolutionError(SANtricityError):
    """Raised when friendly identifiers cannot be resolved to API references."""
