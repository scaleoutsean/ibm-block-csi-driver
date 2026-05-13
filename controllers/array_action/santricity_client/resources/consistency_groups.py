"""Resources related to Consistency Groups (CG)."""

from collections.abc import Mapping
from typing import Any

from .base import ResourceBase


class ConsistencyGroupsResource(ResourceBase):
    """Interact with consistency groups, members, and snapshots."""

    def list_groups(self) -> list[dict[str, Any]]:
        """List all consistency groups."""
        return self._get("/consistency-groups")

    def get_group(self, cg_ref: str) -> dict[str, Any]:
        """Get a specific consistency group by its id."""
        return self._get(f"/consistency-groups/{cg_ref}")

    def create_group(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create a new consistency group."""
        return self._post("/consistency-groups", payload)

    def delete_group(self, cg_ref: str) -> None:
        """Delete a consistency group."""
        self._delete(f"/consistency-groups/{cg_ref}")

    def list_member_volumes(self, cg_ref: str) -> list[dict[str, Any]]:
        """List member volumes of a consistency group."""
        return self._get(f"/consistency-groups/{cg_ref}/member-volumes")

    def add_member_volume(self, cg_ref: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Add a member volume to a consistency group."""
        return self._post(f"/consistency-groups/{cg_ref}/member-volumes", payload)

    def remove_member_volume(self, cg_ref: str, member_ref: str) -> None:
        """Remove a member volume from a consistency group."""
        self._delete(f"/consistency-groups/{cg_ref}/member-volumes/{member_ref}")

    def list_snapshots(self, cg_ref: str) -> list[dict[str, Any]]:
        """List snapshots for a consistency group."""
        return self._get(f"/consistency-groups/{cg_ref}/snapshots")

    def create_snapshot(self, cg_ref: str) -> list[dict[str, Any]]:
        """Create a new snapshot for a consistency group."""
        return self._post(f"/consistency-groups/{cg_ref}/snapshots", {})

    def delete_snapshot(self, cg_ref: str, sequence_number: int) -> None:
        """Delete a consistency group snapshot."""
        # Check SANtricity API specs - standard way to delete CG snapshot is by sequence number
        self._delete(f"/consistency-groups/{cg_ref}/snapshots/{sequence_number}")

    def list_views(self) -> list[dict[str, Any]]:
        """List all consistency group views (Linked Clones across all CGs)."""
        return self._get("/consistency-groups/views")

    def list_views_for_group(self, cg_ref: str) -> list[dict[str, Any]]:
        """List views (Linked Clones) specific to a consistency group."""
        return self._get(f"/consistency-groups/{cg_ref}/views")
