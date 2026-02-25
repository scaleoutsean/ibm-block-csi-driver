"""Volume clone helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import ResourceBase


class ClonesResource(ResourceBase):
    """Create and monitor volume clones."""

    def list(self) -> list[dict[str, Any]]:
        profile = self._client.capabilities
        return self._request_with_fallback(
            "GET",
            profile.clone_endpoint,
            fallback_path=profile.legacy_clone_endpoint,
        )

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        profile = self._client.capabilities
        return self._request_with_fallback(
            "POST",
            profile.clone_endpoint,
            payload=payload,
            fallback_path=profile.legacy_clone_endpoint,
        )
