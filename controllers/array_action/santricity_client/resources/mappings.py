"""Volume mapping helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..exceptions import ResolutionError
from .base import ResourceBase


class VolumeMappingsResource(ResourceBase):
    """Define and list volume-to-host mappings."""

    def list(self) -> list[dict[str, Any]]:
        profile = self._client.capabilities
        return self._request_with_fallback(
            "GET",
            profile.mapping_endpoint,
            fallback_path=profile.legacy_mapping_endpoint,
        )

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        profile = self._client.capabilities
        return self._request_with_fallback(
            "POST",
            profile.mapping_endpoint,
            payload=payload,
            fallback_path=profile.legacy_mapping_endpoint,
        )

    def map_volume(
        self,
        volume_ref: str,
        *,
        host: str | None = None,
        host_ref: str | None = None,
        host_group: str | None = None,
        cluster_ref: str | None = None,
        lun: int | None = None,
        perms: int | None = None,
    ) -> dict[str, Any]:
        target_id = self._resolve_target_id(
            host=host,
            host_ref=host_ref,
            host_group=host_group,
            cluster_ref=cluster_ref,
        )
        payload: dict[str, Any] = {
            "mappableObjectId": volume_ref,
            "targetId": target_id,
        }
        if lun is not None:
            payload["lun"] = lun
        if perms is not None:
            payload["perms"] = perms
        return self.create(payload)

    def move(self, map_ref: str, target_id: str, lun: int | None = None) -> dict[str, Any]:
        """Move a volume mapping to a different host or host group."""
        profile = self._client.capabilities
        path = f"{profile.mapping_endpoint}/{map_ref}/move"
        payload: dict[str, Any] = {"targetId": target_id}
        if lun is not None:
            payload["lun"] = lun

        return self._client.request("POST", path, json_payload=payload)

    def _resolve_target_id(
        self,
        *,
        host: str | None,
        host_ref: str | None,
        host_group: str | None,
        cluster_ref: str | None,
    ) -> str:
        provided = [value for value in (host, host_ref, host_group, cluster_ref) if value]
        if not provided:
            raise ResolutionError(
                "Provide host/host-ref or host-group/cluster-ref when mapping a volume."
            )

        if sum(value is not None for value in (host_ref, cluster_ref)) > 1:
            raise ResolutionError(
                "Specify only one of host-ref or cluster-ref for direct mappings."
            )

        if host_ref and (host or host_group or cluster_ref):
            raise ResolutionError("host-ref cannot be combined with other target options.")
        if cluster_ref and (host or host_group or host_ref):
            raise ResolutionError("cluster-ref cannot be combined with other target options.")

        if host_ref:
            return host_ref
        if cluster_ref:
            return cluster_ref
        if host:
            host_obj = self._client.hosts.find_host(host)
            if not host_obj:
                raise ResolutionError(f"Host '{host}' was not found on the array.")
            resolved_ref = host_obj.get("hostRef")
            if not resolved_ref:
                raise ResolutionError(f"Host '{host}' did not include a hostRef field.")
            return resolved_ref
        if host_group:
            group_obj = self._client.hosts.find_group(host_group)
            if not group_obj:
                raise ResolutionError(f"Host group '{host_group}' was not found on the array.")
            resolved_cluster = group_obj.get("clusterRef")
            if not resolved_cluster:
                raise ResolutionError(
                    f"Host group '{host_group}' did not include a clusterRef field."
                )
            return resolved_cluster

        raise ResolutionError("Unable to resolve mapping target.")
