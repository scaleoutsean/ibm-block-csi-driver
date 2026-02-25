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
            settings["nodeName"] = (
                node_name.get("iscsiNodeName")
                or node_name.get("nvmeNodeName")
                or node_name.get("remoteNodeWWN")
                or "unknown"
            )
        return settings

    def get_nvme_target_settings(self) -> dict[str, Any]:
        """Get NVMeoF target settings, including the target NQN and portals.

        If the direct endpoint does not return portals, it will attempt to
        discover portals by querying the controller interfaces.

        Returns:
            A dictionary containing targetRef, nodeName (NQN), and portals list.
        """
        settings = self._request_with_fallback(
            "GET",
            "/nvmeof/target-settings",
            fallback_path="/nvmeof/initiator-settings",
        )
        node_name = settings.get("nodeName")
        if isinstance(node_name, dict):
            settings["nodeName"] = (
                node_name.get("nvmeNodeName")
                or node_name.get("iscsiNodeName")
                or node_name.get("remoteNodeWWN")
                or "unknown"
            )

        if not settings.get("portals"):
            # Discover portals from interfaces
            portals = []
            for interface in self.list():
                # Skip if physical link is down
                eth_info = (interface.get("ioInterfaceTypeData", {}) or {}).get("ethernet", {})
                if eth_info:
                    link_status = ((eth_info.get("interfaceData") or {}).get("ethernetData") or {}).get("linkStatus")
                    if link_status and link_status.lower() != "up":
                        continue

                # EF600 specific check (based on structure in
                # references/example-EF600-GET-interfaces.json)
                proto_list = interface.get("commandProtocolPropertiesList", {}) or {}
                proto_props = proto_list.get("commandProtocolProperties", []) or []
                for prop in proto_props:
                    if prop.get("commandProtocol") == "nvme":
                        nvme_props = prop.get("nvmeProperties") or {}
                        nvmeof_props = nvme_props.get("nvmeofProperties") or {}
                        # Could be ibProperties, roceV2Properties etc.
                        for props_key in ["ibProperties", "roceV2Properties"]:
                            props = nvmeof_props.get(props_key) or {}
                            
                            # Skip if IP version is not enabled for this specific interface
                            if not props.get("ipv4Enabled", True) and not props.get("ipv6Enabled", False):
                                continue

                            # Check multiple possible paths for IP address across API versions
                            ip = None
                            ipv4_data = props.get("ipv4Data") or {}
                            if isinstance(ipv4_data, dict):
                                # Path 1: ipv4Data.ipv4Address (RoCE - EF600 focus)
                                ip = ipv4_data.get("ipv4Address")
                                if not ip:
                                    # Path 2: ipv4Data.ipv4AddressData.ipv4Address
                                    ip = (ipv4_data.get("ipv4AddressData") or {}).get(
                                        "ipv4Address"
                                    )

                            if not ip:
                                # Path 3: ipAddressData.ipv4Data.ipv4Address (InfiniBand/Older)
                                addr_data = props.get("ipAddressData") or {}
                                ip = (addr_data.get("ipv4Data") or {}).get("ipv4Address")

                            if ip and ip != "0.0.0.0":
                                # If listeningPort is 0 or missing, default to 4420
                                port = props.get("listeningPort") or 4420
                                portals.append(
                                    {
                                        "address": ip,
                                        "port": port,
                                    }
                                )
                                break  # Found an IP for this interface

            if portals:
                settings["portals"] = portals

        return settings

    def get_fc_target_settings(self) -> dict[str, Any]:
        """Get Fibre Channel target interfaces.

        Returns:
            A list of dictionary containing target WWPNs and other details.
        """
        return self._get("/fibre-channel/interface")
