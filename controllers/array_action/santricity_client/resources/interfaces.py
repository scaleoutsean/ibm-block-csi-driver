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

    def get_iscsi_target_settings(self) -> dict[str, Any]:
        """Get iSCSI target settings, including the target IQN and portals.

        Returns:
            A dictionary containing targetRef, nodeName (IQN), and portals list.
        """
        settings = self._get("/iscsi/target-settings")

        node_name = settings.get("nodeName")
        if isinstance(node_name, dict):
            settings["nodeName"] = node_name.get("iscsiNodeName") or ""

        portals = []
        for portal in settings.get("portals") or []:
            ip_address = (portal.get("ipAddress") or {}).get("ipv4Address")
            if not ip_address:
                continue
            portals.append(
                {
                    "address": ip_address,
                    "port": portal.get("tcpListenPort") or 3260,
                }
            )
        settings["portals"] = portals

        return settings

    def _discover_nvme_portals(self) -> list[dict[str, Any]]:
        portals = []
        seen = set()

        for interface in self._get("/interfaces", params={"channelType": "hostside"}):
            proto_list = interface.get("commandProtocolPropertiesList") or {}
            proto_props = proto_list.get("commandProtocolProperties") or []
            for prop in proto_props:
                if prop.get("commandProtocol") != "nvme":
                    continue

                nvmeof_props = ((prop.get("nvmeProperties") or {}).get("nvmeofProperties") or {})
                for props_key in ("roceV2Properties", "ibProperties"):
                    transport_props = nvmeof_props.get(props_key) or {}
                    if not transport_props:
                        continue

                    ipv4_data = transport_props.get("ipv4Data") or {}
                    ipv4_address = ipv4_data.get("ipv4Address") or (
                        (ipv4_data.get("ipv4AddressData") or {}).get("ipv4Address")
                    )
                    if not ipv4_address or ipv4_address == "0.0.0.0":
                        continue

                    listening_port = transport_props.get("listeningPort") or 4420
                    portal_key = (ipv4_address, listening_port)
                    if portal_key in seen:
                        continue

                    portals.append({"address": ipv4_address, "port": listening_port})
                    seen.add(portal_key)

        return portals

    def get_nvme_target_settings(self) -> dict[str, Any]:
        """Get NVMeoF target settings, including the target NQN and portals.

        If the direct endpoint does not return portals, it will attempt to
        discover portals by querying the controller interfaces.

        Returns:
            A dictionary containing targetRef, nodeName (NQN), and portals list.
        """
        settings = self._request_with_fallback(
            "GET",
            "/nvmeof/initiator-settings",
            fallback_path="/nvmeof/target-settings",
        )

        node_name = settings.get("nodeName")
        if isinstance(node_name, dict):
            settings["nodeName"] = node_name.get("nvmeNodeName") or ""

        if not settings.get("portals"):
            portals = self._discover_nvme_portals()
            if portals:
                settings["portals"] = portals

        return settings

    def get_fc_target_settings(self) -> dict[str, Any]:
        """Get Fibre Channel target interfaces.

        Returns:
            A list of dictionary containing target WWPNs and other details.
        """
        return self._get("/fibre-channel/interface")
