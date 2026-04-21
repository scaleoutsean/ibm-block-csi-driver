"""Fixed-shape report builders for SANtricity mappings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time guard
    from ..client import SANtricityClient


def mappings_report(client: SANtricityClient) -> list[dict[str, Any]]:
    """Return a best-effort human-friendly view of volume mappings."""

    vols = client.volumes.list() or []
    pools = client.pools.list() or []
    hosts = client.hosts.list() or []
    host_groups = client.hosts.list_groups() or []
    mappings = client.mappings.list() or []

    vol_by_id: dict[str, dict[str, Any]] = {}
    for volume in vols:
        candidates = (
            volume.get("volumeRef"),
            volume.get("id"),
            volume.get("mappableObjectId"),
            volume.get("mappableObjectRef"),
        )
        for candidate in candidates:
            if candidate:
                vol_by_id.setdefault(str(candidate), volume)

    pool_by_id: dict[str, dict[str, Any]] = {}
    for pool in pools:
        candidates = (
            pool.get("id"),
            pool.get("volumeGroupRef"),
            pool.get("volumeGroupId"),
            pool.get("volumeGroupRef"),
        )
        for candidate in candidates:
            if candidate:
                pool_by_id.setdefault(str(candidate), pool)

    host_by_ref: dict[str, dict[str, Any]] = {}
    for host in hosts:
        candidates = (host.get("hostRef"), host.get("id"), host.get("clusterRef"))
        for candidate in candidates:
            if candidate:
                host_by_ref.setdefault(str(candidate), host)

    group_by_cluster: dict[str, dict[str, Any]] = {}
    for group in host_groups:
        candidates = (group.get("clusterRef"), group.get("id"))
        for candidate in candidates:
            if candidate:
                group_by_cluster.setdefault(str(candidate), group)

    result: list[dict[str, Any]] = []
    for mapping in mappings:
        row: dict[str, Any] = dict(mapping)

        mapping_volume_id = (
            mapping.get("volumeRef")
            or mapping.get("mappableObjectId")
            or mapping.get("mappableObjectRef")
            or mapping.get("mappableObject")
        )
        if mapping_volume_id:
            volume = vol_by_id.get(str(mapping_volume_id))
            if volume:
                volume_name = volume.get("name") or volume.get("label")
                if not volume_name:
                    for fallback_key in (
                        "volumeName",
                        "mappableObjectName",
                        "mappableObjectLabel",
                    ):
                        candidate = volume.get(fallback_key)
                        if candidate:
                            volume_name = candidate
                            break
                if volume_name:
                    row.setdefault("mappableObjectName", volume_name)
                for capacity_key in ("capacity", "reportedSize", "currentVolumeSize"):
                    if capacity_key in volume and volume.get(capacity_key) is not None:
                        row.setdefault("capacity", volume.get(capacity_key))
                        break
                pool_id = (
                    volume.get("volumeGroupRef")
                    or volume.get("poolId")
                    or volume.get("storagePoolId")
                )
                if pool_id:
                    pool = pool_by_id.get(str(pool_id))
                    if pool:
                        pool_name = pool.get("label") or pool.get("name")
                        if not pool_name:
                            for pool_key in ("volumeGroupLabel", "volumeGroupName"):
                                candidate = pool.get(pool_key)
                                if candidate:
                                    pool_name = candidate
                                    break
                        if pool_name:
                            row.setdefault("poolName", pool_name)
                        if pool.get("freeSpace") is not None:
                            row.setdefault("poolFreeSpace", pool.get("freeSpace"))
                        raid = pool.get("raidLevel")
                        if not raid:
                            extents = pool.get("extents")
                            if isinstance(extents, (list, tuple)) and extents:
                                first_extent = extents[0]
                                if isinstance(first_extent, Mapping):
                                    raid = first_extent.get("raidLevel")
                        if raid:
                            row.setdefault("raidLevel", raid)

        candidate_targets = (
            mapping.get("targetId"),
            mapping.get("clusterRef"),
            mapping.get("hostRef"),
            mapping.get("hostGroup"),
            mapping.get("mapRef"),
        )
        best_target_label: str | None = None
        target_resolved = False
        for candidate in candidate_targets:
            if not candidate:
                continue
            key = str(candidate)
            host_obj = host_by_ref.get(key)
            if host_obj:
                host_label = host_obj.get("label") or host_obj.get("name")
                if not host_label:
                    for host_key in ("hostLabel", "hostName"):
                        candidate_label = host_obj.get(host_key)
                        if candidate_label:
                            host_label = candidate_label
                            break
                if host_label:
                    row.setdefault("hostLabel", host_label)
                    best_target_label = host_label
                row.setdefault("hostRef", host_obj.get("hostRef") or host_obj.get("id"))
                target_resolved = True
                break
            group_obj = group_by_cluster.get(key)
            if group_obj:
                group_label = group_obj.get("label") or group_obj.get("name")
                if not group_label:
                    for group_key in ("hostGroupLabel", "clusterName"):
                        candidate_label = group_obj.get(group_key)
                        if candidate_label:
                            group_label = candidate_label
                            break
                if group_label:
                    row.setdefault("hostGroup", group_label)
                    best_target_label = group_label
                row.setdefault("clusterRef", group_obj.get("clusterRef") or group_obj.get("id"))
                target_resolved = True
                break

        if not target_resolved:
            for candidate in candidate_targets:
                if candidate:
                    best_target_label = str(candidate)
                    break

        if not best_target_label:
            for fallback_key in (
                "targetLabel",
                "targetName",
                "hostGroupLabel",
                "clusterName",
                "hostLabel",
            ):
                candidate = row.get(fallback_key)
                if candidate:
                    best_target_label = str(candidate)
                    break

        if best_target_label:
            row.setdefault("targetLabel", best_target_label)

        map_id = (
            mapping.get("mapRef")
            or mapping.get("mappingRef")
            or mapping.get("id")
            or mapping.get("lunMappingRef")
        )
        if map_id:
            row.setdefault("mappingRef", map_id)

        result.append(row)

    return result