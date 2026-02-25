"""Storage pool helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..exceptions import RequestError
from .base import ResourceBase


class PoolsResource(ResourceBase):
    """Work with SANtricity storage pools."""

    def list(self) -> list[dict[str, Any]]:
        return self._get("/storage-pools")

    def get(self, pool_ref: str) -> dict[str, Any]:
        return self._get(f"/storage-pools/{pool_ref}")

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a storage pool by its name or label.

        Args:
            name: The name or label of the storage pool.

        Returns:
            The pool object if found, else None.
        """
        for pool in self.list():
            if pool.get("label") == name or pool.get("name") == name:
                return pool
        return None

    def create_volume(self, pool_ref: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body.setdefault("poolId", pool_ref)
        try:
            return self._post(f"/storage-pools/{pool_ref}/volumes", body)
        except RequestError as exc:
            if exc.status_code in (404, 405):
                # Older releases only expose the legacy /volumes endpoint.
                return self._client.volumes.create(body)
            raise
