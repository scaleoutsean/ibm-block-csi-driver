"""HTTP Basic authentication support."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass

from .base import AuthStrategy


@dataclass(slots=True)
class BasicAuth(AuthStrategy):
    """Apply HTTP Basic auth headers."""

    username: str
    password: str

    # pragma: no cover - requests handles encoding internally
    def apply(self, headers: MutableMapping[str, str]) -> None:
        from requests.auth import _basic_auth_str

        headers["Authorization"] = _basic_auth_str(self.username, self.password)
