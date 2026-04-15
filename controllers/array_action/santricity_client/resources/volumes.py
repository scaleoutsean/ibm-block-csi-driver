"""Volume operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import ResourceBase


class VolumesResource(ResourceBase):
    """Interact with SANtricity volumes."""

    def list(self) -> list[dict[str, Any]]:
        return self._get("/volumes")

    def get(self, volume_ref: str) -> dict[str, Any]:
        return self._get(f"/volumes/{volume_ref}")

    def get_volume_by_name(self, name: str, pool_name: str | None = None) -> dict[str, Any] | None:
        """Find a volume by its name or label, optionally filtering by pool name.

        Args:
            name: The name or label of the volume.
            pool_name: Optional name or label of the storage pool containing the volume.

        Returns:
            The volume object if found, else None.
        """
        target_pool_ref = None
        if pool_name:
            pool = self._client.pools.get_by_name(pool_name)
            if not pool:
                return None
            target_pool_ref = pool.get("volumeGroupRef") or pool.get("id")

        for volume in self.list():
            if volume.get("label") == name or volume.get("name") == name:
                if target_pool_ref and volume.get("volumeGroupRef") != target_pool_ref:
                    continue
                return volume
        return None

    def delete(self, volume_ref: str) -> dict[str, Any]:
        return self._delete(f"/volumes/{volume_ref}")

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post("/volumes", payload)

    def map_to_host(self, volume_ref: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post(f"/volumes/{volume_ref}/mappings", payload)

    def expand(
        self, volume_ref: str, expansion_size: float | int, unit: str = "bytes"
    ) -> dict[str, Any]:
        """Expand a volume to a new target capacity.

        Args:
            volume_ref: The volume reference.
            expansion_size: The new target capacity.
            unit: The unit of the expansion size.
                  Supported units: bytes, mb, gb, tb, mib, gib, tib.
                  mb/gb/tb are treated as decimal (powers of 1000).
                  mib/gib/tib are treated as binary (powers of 1024).

        Returns:
            A dictionary containing the expansion progress details.
        """
        unit_multipliers = {
            "bytes": 1,
            "b": 1,
            "mb": 1000**2,
            "gb": 1000**3,
            "tb": 1000**4,
            "mib": 1024**2,
            "gib": 1024**3,
            "tib": 1024**4,
        }

        normalized_unit = unit.lower()
        if normalized_unit not in unit_multipliers:
            raise ValueError(
                f"Invalid unit: {unit}. Supported units: {', '.join(unit_multipliers.keys())}"
            )

        size_bytes = int(expansion_size * unit_multipliers[normalized_unit])

        payload = {"expansionSize": size_bytes, "sizeUnit": "bytes"}

        return self._post(f"/volumes/{volume_ref}/expand", payload)
