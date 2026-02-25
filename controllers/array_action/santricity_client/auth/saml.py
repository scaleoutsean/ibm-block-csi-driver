"""Placeholder SAML2 strategy."""

from __future__ import annotations

from collections.abc import MutableMapping

from .base import AuthStrategy


class SAMLAuthStub(AuthStrategy):
    """Non-functional placeholder that documents the expected interface."""

    def __init__(self, assertion: str | None = None) -> None:
        self.assertion = assertion

    def apply(self, headers: MutableMapping[str, str]) -> None:  # pragma: no cover - stub
        raise NotImplementedError(
            "SAMLAuthStub is a placeholder. Provide an assertion handler before enabling."
        )
