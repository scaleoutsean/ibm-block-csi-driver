"""Snapshot helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..exceptions import RequestError
from .base import ResourceBase


class SnapshotsResource(ResourceBase):
    """Interact with snapshot groups, images, volumes, repositories, and schedules."""

    def list_groups(self) -> list[dict[str, Any]]:
        return self._get("/snapshot-groups")

    def create_group(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post("/snapshot-groups", payload)

    def create_snapshot_group(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create a snapshot group from a full payload."""
        return self.create_group(payload)

    def delete_group(self, group_ref: str) -> None:
        """Delete a snapshot group by pitGroupRef / id."""
        self._delete(f"/snapshot-groups/{group_ref}")

    def delete_snapshot_group(self, group_ref: str) -> None:
        """Alias for deleting a snapshot group by reference."""
        self.delete_group(group_ref)

    def list_images(self, group_ref: str) -> list[dict[str, Any]]:
        """List snapshot images scoped to a specific snapshot group."""
        return self._get(f"/snapshot-groups/{group_ref}/images")

    def create_image(self, group_ref: str) -> dict[str, Any]:
        """Create a new snapshot image for a snapshot group id.

        Preferred endpoint is POST /snapshot-images with a groupId payload,
        matching the current SANtricity UI/API workflow. Fallback preserves
        compatibility with arrays exposing the group-scoped images endpoint.
        """
        try:
            return self._post("/snapshot-images", {"groupId": group_ref})
        except RequestError as exc:
            if exc.status_code in (400, 404, 405):
                return self._post(f"/snapshot-groups/{group_ref}/images", {})
            raise

    def create_snapshot(self, group_ref: str) -> dict[str, Any]:
        """Create a snapshot image for the given snapshot group ref."""
        return self.create_image(group_ref)

    def delete_image(self, image_ref: str) -> None:
        """Delete a snapshot image by its pitRef / id."""
        self._delete(f"/snapshot-images/{image_ref}")

    def delete_snapshot(self, snapshot_ref: str) -> None:
        """Delete a snapshot image by snapshot ref."""
        self.delete_image(snapshot_ref)

    def list_all_images(self) -> list[dict[str, Any]]:
        """List all snapshot images across all snapshot groups."""
        return self._get("/snapshot-images")

    def list_volumes(self) -> list[dict[str, Any]]:
        """List snapshot volumes (linked clones and read-only views)."""
        return self._get("/snapshot-volumes")

    def list_repositories(self) -> list[dict[str, Any]]:
        """List concatenated repository volumes backing snapshot groups and linked clones."""
        return self._get("/repositories/concat")

    def expand_repository(
        self,
        repository_ref: str,
        expansion_candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Expand a concat repository volume with a chosen candidate."""
        payload: dict[str, Any] = {
            "repositoryRef": repository_ref,
            "expansionCandidate": dict(expansion_candidate),
        }
        return self._post(f"/repositories/concat/{repository_ref}/expand", payload)

    def get_repo_group_candidates_single(
        self,
        base_volume_ref: str,
        percent_capacity: int,
        *,
        use_free_repository_volumes: bool = False,
        concat_volume_type: str = "snapshot",
    ) -> list[dict[str, Any]]:
        """Return repo-group candidates for a single base volume.

        SANtricity does not expose a standalone "create repository group" endpoint.
        The candidate returned here is typically consumed by snapshot-group or
        snapshot-volume creation requests.
        """
        payload: dict[str, Any] = {
            "useFreeRepositoryVolumes": use_free_repository_volumes,
            "candidateRequest": {
                "baseVolumeRef": base_volume_ref,
                "percentCapacity": percent_capacity,
                "concatVolumeType": concat_volume_type,
            },
        }
        return self._post("/repositories/concat/single", payload)

    def create_repo_group_single(
        self,
        base_volume_ref: str,
        percent_capacity: int,
        *,
        use_free_repository_volumes: bool = False,
        concat_volume_type: str = "snapshot",
    ) -> list[dict[str, Any]]:
        """Backward-compatible alias for repo-group candidate selection."""
        return self.get_repo_group_candidates_single(
            base_volume_ref=base_volume_ref,
            percent_capacity=percent_capacity,
            use_free_repository_volumes=use_free_repository_volumes,
            concat_volume_type=concat_volume_type,
        )

    def list_group_repo_utilization(self) -> list[dict[str, Any]]:
        """List repository utilization for each snapshot group."""
        return self._get("/snapshot-groups/repository-utilization")

    def list_volume_repo_utilization(self) -> list[dict[str, Any]]:
        """List repository utilization for each snapshot volume (linked clone)."""
        return self._get("/snapshot-volumes/repository-utilization")

    def list_async_mirror_repo_utilization(self) -> list[dict[str, Any]]:
        """List repository utilization for async mirror pairs (all-flash arrays may return 404)."""
        return self._get("/async-mirrors/pairs/repository-utilization")

    def list_consistency_group_members(self) -> list[dict[str, Any]]:
        """List volumes that are members of consistency groups."""
        return self._get("/consistency-groups/member-volumes")

    def list_schedules(self) -> list[dict[str, Any]]:
        """List snapshot schedules tied to snapshot groups."""
        return self._get("/snapshot-schedules")
