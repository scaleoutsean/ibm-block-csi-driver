"""JWT bearer token authentication."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass

from .base import AuthStrategy


@dataclass(slots=True)
class JWTAuth(AuthStrategy):
    """Apply an already issued bearer token."""

    token: str

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self.token}"

    def update_token(self, token: str) -> None:
        self.token = token
