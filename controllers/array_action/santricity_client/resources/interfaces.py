"""Interface module."""

from __future__ import annotations

from typing import Any

from .base import ResourceBase


class InterfacesResource(ResourceBase):
    """Access controller interface metadata."""

    def list(self) -> list[dict[str, Any]]:
        return self._get("/interfaces")

    def get(self, interface_id: str) -> dict[str, Any]:
        return self._get(f"/interfaces/{interface_id}")

    def get_system_hostside_interfaces(self) -> list[dict[str, Any]]:
        """Get host-side interfaces from `/interfaces`.

        Returns:
            A list of host-side interface dictionaries.
        """

        interfaces = self.list() or []
        return [
            interface
            for interface in interfaces
            if str(interface.get("channelType", "")).lower() == "hostside"
        ]

    def get_iscsi_target_settings(self) -> dict[str, Any]:
        """Get iSCSI target settings, including the target IQN and portals.

        Returns:
            A dictionary containing targetRef, nodeName (IQN), and portals list.
        """
        return self._get("/iscsi/target-settings")

    def get_nvme_target_settings(self) -> dict[str, Any]:
        """Get NVMeoF target settings, including the target NQN and portals.

        This method only reads `/nvmeof/initiator-settings` and returns the
        API response as-is.

        Returns:
            A dictionary containing targetRef, nodeName (NQN), and portals list.
        """
        return self._get("/nvmeof/initiator-settings")

