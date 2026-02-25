"""Host abstractions."""

from __future__ import annotations

from typing import Any

from .base import ResourceBase


class HostsResource(ResourceBase):
    """Manage hosts and host groups."""

    def list(self) -> list[dict[str, Any]]:
        return self._get("/hosts")

    def get(self, host_ref: str) -> dict[str, Any]:
        return self._get(f"/hosts/{host_ref}")

    def delete(self, host_ref: str) -> dict[str, Any]:
        """Delete an existing host.

        Args:
            host_ref: The host reference.
        """
        return self._delete(f"/hosts/{host_ref}")

    def create(
        self,
        name: str,
        index: int = 28,
        port: str = "",
        port_type: str = "iscsi",
        iscsi_chap_secret: str | None = None,
    ) -> dict[str, Any]:
        """Create a new host with one port/initiator.

        Args:
            name: The host name.
            index: The host type index (28 for Linux).
            port: The initiator identifier, such as IQN (iSCSI), NQN (NVMe), or WWN (FC).
            port_type: The port type, such as "iscsi", "nvmeof", "fc", or "nvmeRoce".
            iscsi_chap_secret: Optional iSCSI CHAP secret.
        """
        port_data: dict[str, Any] = {
            "label": f"{name}_1",
            "port": port,
            "type": port_type,
        }
        if iscsi_chap_secret:
            port_data["iscsiChapSecret"] = iscsi_chap_secret

        payload = {
            "name": name,
            "hostType": {"index": index},
            "ports": [port_data],
        }
        return self._post("/hosts", payload)

    def update(
        self,
        host_ref: str,
        name: str | None = None,
        index: int | None = None,
        group_id: str | None = None,
        ports: list[dict[str, Any]] | None = None,
        ports_to_update: list[dict[str, Any]] | None = None,
        ports_to_remove: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing host.

        Args:
            host_ref: The host reference.
            name: Optional new label.
            index: Optional new host type index.
            group_id: Optional group ID to move the host to.
            ports: Optional list of new ports to add.
            ports_to_update: Optional list of existing ports to update.
            ports_to_remove: Optional list of port refs to remove.
        """
        payload: dict[str, Any] = {}
        if name:
            payload["name"] = name
        if index is not None:
            payload["hostType"] = {"index": index}
        if group_id:
            payload["groupId"] = group_id
        if ports:
            payload["ports"] = ports
        if ports_to_update:
            payload["portsToUpdate"] = ports_to_update
        if ports_to_remove:
            payload["portsToRemove"] = ports_to_remove

        return self._post(f"/hosts/{host_ref}", payload)

    def add_initiator(
        self,
        host_ref: str,
        name: str,
        type: str = "iscsi",
        chap_secret: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Add an initiator to a host.

        Args:
            host_ref: The host reference.
            name: The initiator identifier (IQN for iSCSI, NQN for NVMe, WWN for FC).
            type: The interface type, e.g., "iscsi", "nvmeof", "fc".
            chap_secret: Optional CHAP secret (iSCSI only).
            label: Optional user label for the initiator.
        """
        payload = {
            "type": type,
            "port": name,
        }
        if label:
            payload["label"] = label
        if chap_secret:
            payload["iscsiChapSecret"] = chap_secret

        return self._post(f"/hosts/{host_ref}/initiators", payload)

    def list_groups(self) -> list[dict[str, Any]]:
        return self._get("/host-groups")

    def get_group(self, group_ref: str) -> dict[str, Any]:
        return self._get(f"/host-groups/{group_ref}")

    def delete_group(self, group_ref: str, force: bool = False) -> dict[str, Any]:
        """Delete an existing host group.

        Args:
            group_ref: The host group reference.
            force: If True, delete group even if it contains hosts.
                   If False (default), fail if group is not empty.
        """
        if not force:
            hosts = self.list()
            group_hosts = [h for h in hosts if h.get("clusterRef") == group_ref]
            if group_hosts:
                from ..exceptions import RequestError

                raise RequestError(
                    f"Host group {group_ref} is not empty and force=False. "
                    f"Hosts: {[h.get('label') for h in group_hosts]}",
                    status_code=400,
                )

        return self._delete(f"/host-groups/{group_ref}")

    def create_group(self, name: str, hosts: list[str] | None = None) -> dict[str, Any]:
        """Create a new host group.

        Args:
            name: The host group name.
            hosts: Optional list of host references to add to the group.
        """
        payload = {"name": name}
        if hosts:
            payload["hosts"] = hosts
        return self._post("/host-groups", payload)

    def update_group(
        self,
        group_ref: str,
        name: str | None = None,
        hosts: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing host group.

        Args:
            group_ref: The host group reference.
            name: Optional new label.
            hosts: Optional new list of host references.
        """
        payload: dict[str, Any] = {}
        if name:
            payload["name"] = name
        if hosts is not None:
            payload["hosts"] = hosts

        return self._post(f"/host-groups/{group_ref}", payload)

    def find_host(self, label: str) -> dict[str, Any] | None:
        """Find a host by its label (deprecated, use get_by_name)."""
        return self.get_by_name(label)

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a host by its label or name.

        Args:
            name: The host label or name.
        """
        for host in self.list():
            if host.get("label") == name or host.get("name") == name:
                return host
        return None

    def get_by_identifiers(self, identifier: str) -> dict[str, Any] | None:
        """Find a host by its name, ID, or port address.

        Args:
            identifier: The host name, label, hostRef, WWN, or initiator port (address).
        """
        for host in self.list():
            if (
                host.get("label") == identifier
                or host.get("name") == identifier
                or host.get("id") == identifier
                or host.get("hostRef") == identifier
            ):
                return host

            for port in host.get("hostSidePorts", []):
                if port.get("address") == identifier:
                    return host

            for initiator in host.get("initiators", []):
                node_name = initiator.get("nodeName", {}) or {}
                if (
                    node_name.get("iscsiNodeName") == identifier
                    or node_name.get("nvmeNodeName") == identifier
                    or node_name.get("remoteNodeWWN") == identifier
                ):
                    return host

        return None

    def get_mapping_target(self, identifier: str) -> dict[str, Any] | None:
        """Find the correct target for volume mapping (either the host or its group).

        If the identifier refers to a host that is part of a host group, it returns
        the host group object. Otherwise, it returns the host object or None.

        Args:
            identifier: The host name, label, hostRef, WWN, or initiator port (address).
        """
        host = self.get_by_identifiers(identifier)
        if not host:
            # Maybe it's a group name/ID directly?
            return self.find_group(identifier)

        group_ref = host.get("clusterRef")
        if group_ref and group_ref != "0000000000000000000000000000000000000000":
            return self.get_group(group_ref)

        return host

    # Aliases
    get_host_by_name = get_by_name
    get_host_by_host_identifiers = get_by_identifiers

    def find_group(self, identifier: str) -> dict[str, Any] | None:
        """Find a host group by its label or ID.

        Args:
            identifier: The host group label, name, or ID (clusterRef).
        """
        for group in self.list_groups():
            if (
                group.get("label") == identifier
                or group.get("name") == identifier
                or group.get("id") == identifier
                or group.get("clusterRef") == identifier
            ):
                return group
        return None
