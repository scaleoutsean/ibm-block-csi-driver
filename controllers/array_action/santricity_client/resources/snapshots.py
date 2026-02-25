"""Snapshot helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import ResourceBase


class SnapshotsResource(ResourceBase):
    """Interact with snapshot groups and images."""

    def list_groups(self) -> list[dict[str, Any]]:
        return self._get("/snapshot-groups")

    def create_group(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post("/snapshot-groups", payload)

    def list_images(self, group_ref: str) -> list[dict[str, Any]]:
        return self._get(f"/snapshot-groups/{group_ref}/images")
