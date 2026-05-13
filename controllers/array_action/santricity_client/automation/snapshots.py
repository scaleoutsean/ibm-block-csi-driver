"""Snapshot workflow helpers that orchestrate multiple raw API calls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover - import-time guard
    from ..client import SANtricityClient

logger = logging.getLogger(__name__)


def _coerce_int_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, TypeError):
        return default


def _pick_group_field_int(group: Mapping[str, Any], *fields: str) -> int:
    for field in fields:
        val = group.get(field)
        if val is not None:
            return _coerce_int_default(val, 0)
    return 0


def _snapshot_schedule_counts(schedules: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sched in schedules:
        obj_ref = str(sched.get("targetObject") or sched.get("id") or "")
        counts[obj_ref] = counts.get(obj_ref, 0) + 1
    return counts


class SnapshotsAutomation:
    """Namespace for higher-level snapshot automation workflows."""

    def __init__(self, client: SANtricityClient) -> None:
        self._client = client

    def _choose_snapshot_group_for_auto(
        self,
        groups: Sequence[Mapping[str, Any]],
        schedules: Sequence[Mapping[str, Any]],
        utilization: Sequence[Mapping[str, Any]],
        repositories: Sequence[Mapping[str, Any]],
        volume_ref: str,
        include_schedule_owned_groups: bool,
        min_free_percent: float,
        max_repo_group_capacity_percent: float,
        max_repo_volumes_per_group: int,
    ) -> tuple[str | None, dict[str, Any] | None]:
        schedule_counts = _snapshot_schedule_counts(schedules)
        util_by_group_ref: dict[str, Mapping[str, Any]] = {
            str(item.get("groupRef") or ""): item
            for item in utilization
            if item.get("groupRef")
        }
        repo_by_ref: dict[str, Mapping[str, Any]] = {
            str(item.get("id") or item.get("repositoryRef") or item.get("concatRef") or ""): item
            for item in repositories
            if item.get("id") or item.get("repositoryRef") or item.get("concatRef")
        }

        eligible: list[tuple[int, int, str]] = []
        grow_candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []

        for group in groups:
            group_ref = str(group.get("pitGroupRef") or group.get("id") or "")
            if not group_ref:
                continue
            if str(group.get("baseVolume") or "") != volume_ref:
                continue

            schedule_count = schedule_counts.get(group_ref, 0)
            if schedule_count > 0 and not include_schedule_owned_groups:
                continue

            util = util_by_group_ref.get(group_ref, {})
            available = _coerce_int_default(util.get("pitGroupBytesAvailable"), 0)
            used = _coerce_int_default(util.get("pitGroupBytesUsed"), 0)

            base_bytes = _pick_group_field_int(group, "maxBaseCapacity", "baseVolumeCapacity")
            if base_bytes <= 0:
                base_bytes = available + used

            min_free_bytes = int(base_bytes * (min_free_percent / 100.0)) if base_bytes > 0 else 0
            repo_capacity_bytes = _pick_group_field_int(group, "repositoryCapacity")
            if repo_capacity_bytes <= 0:
                repo_capacity_bytes = available + used

            current_repo_percent = (repo_capacity_bytes / base_bytes * 100.0) if base_bytes > 0 else 0.0

            snapshot_count = _coerce_int_default(group.get("snapshotCount"), 0)
            if available >= min_free_bytes:
                eligible.append((available, -snapshot_count, group_ref))
                continue

            if current_repo_percent >= max_repo_group_capacity_percent:
                continue

            repository_ref = str(group.get("repositoryVolume") or "")
            repository = repo_by_ref.get(repository_ref, {}) if repository_ref else {}
            member_count = _pick_group_field_int(
                repository,
                "memberCount",
                "totalRepositoryVolumes",
                "repositoryVolumeCount",
                "volumeCount",
            )
            if member_count <= 0 and isinstance(repository.get("members"), list):
                member_count = len(repository["members"])
            if member_count >= max_repo_volumes_per_group:
                continue

            grow_candidates.append(
                (
                    available,
                    -snapshot_count,
                    -member_count,
                    group_ref,
                    {
                        "groupRef": group_ref,
                        "repositoryRef": repository_ref,
                        "baseVolumeRef": str(group.get("baseVolume") or ""),
                        "availableBytes": available,
                        "minFreeBytes": min_free_bytes,
                        "memberCount": member_count,
                    },
                )
            )

        if eligible:
            eligible.sort(reverse=True)
            return eligible[0][2], None

        if grow_candidates:
            grow_candidates.sort(reverse=True)
            return None, grow_candidates[0][4]

        return None, None

    def auto_create_snapshot(
        self,
        volume_ref: str,
        name: str | None = None,
        min_free_percent: float = 10.0,
        growth_step_percent: float = 10.0,
        auto_grow_if_needed: bool = True,
        include_schedule_owned_groups: bool = True,
        max_repo_group_capacity_percent: float = 200.0,
        max_repo_volumes_per_group: int = 16,
        initial_repo_group_size_pct: int | None = 20,
    ) -> dict[str, Any]:
        """Automatically create a snapshot image for a volume.
        
        - Tries to find an eligible snapshot group with enough free capacity.
        - Tries to expand an eligible group if none have enough free capacity.
        - Falls back to creating a new snapshot group if none exist or all are full.
        """
        groups = self._client.snapshots.list_groups()
        schedules = self._client.snapshots.list_schedules()
        utilization = self._client.snapshots.list_group_repo_utilization()
        repositories = self._client.snapshots.list_repositories()

        resolved_group_ref, grow_target = self._choose_snapshot_group_for_auto(
            groups=groups,
            schedules=schedules,
            utilization=utilization,
            repositories=repositories,
            volume_ref=volume_ref,
            include_schedule_owned_groups=include_schedule_owned_groups,
            min_free_percent=min_free_percent,
            max_repo_group_capacity_percent=max_repo_group_capacity_percent,
            max_repo_volumes_per_group=max_repo_volumes_per_group,
        )

        if not resolved_group_ref and grow_target and auto_grow_if_needed:
            candidates = self._client.snapshots.get_repo_group_candidates_single(
                base_volume_ref=str(grow_target.get("baseVolumeRef") or ""),
                percent_capacity=int(growth_step_percent),
                use_free_repository_volumes=False,
                concat_volume_type="snapshot",
            )
            candidate = candidates[0].get("candidate") if isinstance(candidates, list) and candidates else None
            repository_ref = str(grow_target.get("repositoryRef") or "")
            if candidate and repository_ref:
                self._client.snapshots.expand_repository(
                    repository_ref=repository_ref,
                    expansion_candidate=candidate,
                )
                resolved_group_ref = str(grow_target.get("groupRef") or "")
                logger.info("Expanded snapshot group {%s} by {%s}%%", resolved_group_ref, growth_step_percent)

        if not resolved_group_ref:
            # We must create a new snapshot group for this volume!
            logger.info("No eligible snapshot group found for volume {%s}, creating a new one.", volume_ref)
            effective_initial_repo_group_size_pct = int(initial_repo_group_size_pct or 20)
            candidates = self._client.snapshots.get_repo_group_candidates_single(
                base_volume_ref=volume_ref,
                percent_capacity=effective_initial_repo_group_size_pct,
                concat_volume_type="snapshot"
            )
            if not candidates:
                 raise Exception(f"No repository candidates found to create a new group for volume {volume_ref}")
                 
            group_payload = {
                "baseMappableObjectId": volume_ref,
                "name": name or "auto_snapshot_group",
                "repositoryCandidate": candidates[0].get("candidate")
            }
            group_data = self._client.snapshots.create_group(group_payload)
            resolved_group_ref = group_data["id"]

            logger.info("group_payload: %s", group_payload)
        # Now take the snapshot in the resolved group
        logger.info("Taking snapshot image in group {%s}", resolved_group_ref)
        image_data = self._client.snapshots.create_image(resolved_group_ref)
        return image_data

    def create_cg_snapshot(self, cg_ref: str) -> list[dict[str, Any]]:
        """Take a snapshot of a Consistency Group, verifying members exist first."""
        members = self._client.consistency_groups.list_member_volumes(cg_ref)
        if not members:
            raise RuntimeError(f"Cannot take snapshot of consistency group '{cg_ref}': it has no member volumes.")
        
        return self._client.consistency_groups.create_snapshot(cg_ref)
