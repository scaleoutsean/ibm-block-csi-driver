"""Host-side interface report helpers."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from ..exceptions import RequestError

logger = logging.getLogger(__name__)

INDEXED_PATH_PART = re.compile(r"^(?P<key>[^\[\]]+)(?:\[(?P<index>\d+)\])?$")

FieldTransform = Callable[[Any], Any]
FieldMapping = tuple[str, str, FieldTransform | None]


def _lower_string(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip().lower()
        return cleaned or None
    return None


def _strip_string(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _convert_link_status_to_bool(value: Any) -> bool:
    if isinstance(value, str):
        value_lower = value.strip().lower()
        if value_lower == "up":
            return True
        if value_lower == "down":
            return False
    raise ValueError(f"Unexpected link status value: {value!r}")


def _convert_speed_string_to_mebibits_per_second(value: Any) -> int | None:
    if isinstance(value, str):
        value_lower = value.strip().lower()
        if value_lower in {"speedunknown", "__undefined", "unknown", ""}:
            return None
        if value_lower.startswith("speed") and value_lower.endswith("gig"):
            try:
                gig_value = int(value_lower[5:-3])
            except ValueError as exc:
                raise ValueError(f"Unexpected speed string format: {value!r}") from exc
            return gig_value * 1000
    raise ValueError(f"Unexpected speed string format: {value!r}")


def _convert_fc_speed_code_to_mebibits_per_second(value: Any) -> int | None:
    if value in {0, None}:
        return None
    if isinstance(value, int):
        return value * 10
    raise ValueError(f"Unexpected FC speed value: {value!r}")


def _format_wwn(value: Any) -> str | None:
    cleaned = _strip_string(value)
    if cleaned is None:
        return None
    normalized = cleaned.replace(":", "")
    return ":".join(normalized[index : index + 2] for index in range(0, len(normalized), 2))


def _list_to_semicolon_string(
    value: Any,
    item_transform: Callable[[Any], Any | None] | None = None,
) -> str | None:
    if not isinstance(value, list):
        raise ValueError(f"Unexpected list value: {value!r}")
    items: list[str] = []
    for item in value:
        transformed = item_transform(item) if item_transform else item
        if transformed is None:
            continue
        items.append(str(transformed))
    if not items:
        return None
    return ";".join(items)


def _speed_list_to_semicolon_string(value: Any) -> str | None:
    return _list_to_semicolon_string(value, _convert_speed_string_to_mebibits_per_second)


def _normalize_report_protocol(value: Any) -> str | None:
    normalized = _lower_string(value)
    if normalized == "fc":
        return "fibre"
    if normalized == "infiniband":
        return "ib"
    return normalized


def _normalize_command_provider(value: Any) -> str | None:
    normalized = _lower_string(value)
    if normalized is None:
        return None
    aliases = {
        "providerrocev2": "provider_roce_v2",
        "providerinfiniband": "provider_infiniband",
    }
    return aliases.get(normalized, normalized)


def _normalize_filter_value(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "*": "all",
        "fc": "fibre",
        "fiber": "fibre",
        "fibre_channel": "fibre",
        "infiniband": "ib",
    }
    return aliases.get(normalized, normalized)


COMMON_FIELDS: list[FieldMapping] = [
    ("controllerRef", "controller_ref", _strip_string),
    ("interfaceRef", "interface_ref", _strip_string),
    ("channelType", "channel_type", _lower_string),
    ("ioInterfaceTypeData_interfaceType", "protocol", _normalize_report_protocol),
]

HOSTSIDE_INTERFACE_ISCSI: list[FieldMapping] = [
    ("channel", "channel", _coerce_int),
    ("channelPortRef", "channel_port_ref", _strip_string),
    ("tcpListenPort", "tcp_listen_port", _coerce_int),
    ("ipv4Enabled", "is_ipv4_enabled", None),
    ("ipv4Data_ipv4Address", "ipv4_address", _strip_string),
    ("interfaceData_type", "transport", _normalize_report_protocol),
    (
        "interfaceData_ethernetData_maximumFramePayloadSize",
        "maximum_mtu_bytes",
        _coerce_int,
    ),
    (
        "interfaceData_ethernetData_currentInterfaceSpeed",
        "current_interface_speed_mebibits_per_second",
        _convert_speed_string_to_mebibits_per_second,
    ),
    (
        "interfaceData_ethernetData_maximumInterfaceSpeed",
        "maximum_interface_speed_mebibits_per_second",
        _convert_speed_string_to_mebibits_per_second,
    ),
    ("iqn", "iqn", _strip_string),
    ("controllerId", "controller_id", _strip_string),
    ("interfaceId", "interface_id", _strip_string),
    ("addressId", "address_id", _strip_string),
    ("id", "id", _strip_string),
]

HOSTSIDE_INTERFACE_IB: list[FieldMapping] = [
    ("interfaceId", "interface_id", _strip_string),
    ("channel", "channel", _coerce_int),
    ("channelPortRef", "channel_port_ref", _strip_string),
    ("linkState", "link_state", _lower_string),
    ("portState", "port_state", _lower_string),
    ("maximumTransmissionUnit", "maximum_mtu_bytes", _coerce_int),
    (
        "currentSpeed",
        "current_interface_speed_mebibits_per_second",
        _convert_speed_string_to_mebibits_per_second,
    ),
    (
        "supportedSpeed",
        "supported_speeds_mebibits_per_second_list",
        _speed_list_to_semicolon_string,
    ),
    ("currentLinkWidth", "current_link_width", _lower_string),
    ("supportedLinkWidth", "supported_link_widths_list", _list_to_semicolon_string),
    ("currentDataVirtualLanes", "current_data_virtual_lane_count", _coerce_int),
    ("maximumDataVirtualLanes", "maximum_data_virtual_lane_count", _coerce_int),
    ("isNVMeSupported", "is_nvme_supported", None),
    ("controllerId", "controller_id", _strip_string),
    ("addressId", "address_id", _strip_string),
    ("id", "id", _strip_string),
]

HOSTSIDE_INTERFACE_ETHERNET: list[FieldMapping] = [
    ("interfaceId", "interface_id", _strip_string),
    ("channel", "channel", _coerce_int),
    ("channelPortRef", "channel_port_ref", _strip_string),
    ("interfaceData_type", "transport", _normalize_report_protocol),
    ("interfaceData_ethernetData_macAddress", "mac_address", _strip_string),
    (
        "interfaceData_ethernetData_maximumFramePayloadSize",
        "maximum_mtu_bytes",
        _coerce_int,
    ),
    (
        "interfaceData_ethernetData_currentInterfaceSpeed",
        "current_interface_speed_mebibits_per_second",
        _convert_speed_string_to_mebibits_per_second,
    ),
    (
        "interfaceData_ethernetData_maximumInterfaceSpeed",
        "maximum_interface_speed_mebibits_per_second",
        _convert_speed_string_to_mebibits_per_second,
    ),
    ("interfaceData_ethernetData_linkStatus", "link_status", _lower_string),
    ("controllerId", "controller_id", _strip_string),
    ("addressId", "address_id", _strip_string),
    ("id", "id", _strip_string),
]

HOSTSIDE_INTERFACE_FIBRE: list[FieldMapping] = [
    ("channel", "channel", _coerce_int),
    ("speed", "speed_mebibits_per_second", _convert_fc_speed_code_to_mebibits_per_second),
    ("nodeName", "node_name", _format_wwn),
    ("topology", "topology", _lower_string),
    ("chanMiswire", "is_channel_miswired", None),
    ("esmMiswire", "is_esm_miswired", None),
    ("linkStatus", "link_status", _lower_string),
    ("linkStatus", "is_link_up", _convert_link_status_to_bool),
    ("isDegraded", "is_degraded", None),
    ("speedControl", "speed_control", _lower_string),
    (
        "maxSpeed",
        "max_speed_mebibits_per_second",
        _convert_fc_speed_code_to_mebibits_per_second,
    ),
    ("speedNegError", "is_speed_negotiation_error", None),
    ("isLocal", "is_local", None),
    (
        "currentInterfaceSpeed",
        "current_interface_speed_mebibits_per_second",
        _convert_speed_string_to_mebibits_per_second,
    ),
    ("isTrunkCapable", "is_trunk_capable", None),
    ("trunkMiswire", "is_trunk_miswired", None),
    ("interfaceId", "interface_id", _strip_string),
    ("addressId", "address_id", _strip_string),
    ("id", "id", _strip_string),
]

PROTOCOL_FIELD_MAPPINGS: dict[str, list[FieldMapping]] = {
    "ethernet": HOSTSIDE_INTERFACE_ETHERNET,
    "iscsi": HOSTSIDE_INTERFACE_ISCSI,
    "ib": HOSTSIDE_INTERFACE_IB,
    "fibre": HOSTSIDE_INTERFACE_FIBRE,
}

COMMAND_PROTOCOL_COMMON_FIELDS: list[FieldMapping] = [
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_commandProtocol",
        "command_protocol",
        _lower_string,
    ),
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_nvmeProperties_nvmeofProperties_provider",
        "command_provider",
        _normalize_command_provider,
    ),
]

COMMAND_PROTOCOL_IB_FIELDS: list[FieldMapping] = [
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_nvmeProperties_nvmeofProperties_ibProperties_ipAddressData_ipv4Data_configState",
        "infiniband_ipv4_config_state",
        _lower_string,
    ),
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_nvmeProperties_nvmeofProperties_ibProperties_ipAddressData_ipv4Data_ipv4Address",
        "infiniband_ipv4_address",
        _strip_string,
    ),
]

COMMAND_PROTOCOL_ROCE_V2_FIELDS: list[FieldMapping] = [
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_nvmeProperties_nvmeofProperties_roceV2Properties_ipv4Enabled",
        "is_roce_v2_ipv4_enabled",
        None,
    ),
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_nvmeProperties_nvmeofProperties_roceV2Properties_ipv4Data_ipv4Address",
        "roce_v2_ipv4_address",
        _strip_string,
    ),
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_nvmeProperties_nvmeofProperties_roceV2Properties_ipv4Data_ipv4OutboundPacketPriority_isEnabled",
        "is_roce_v2_pfc_enabled",
        None,
    ),
    (
        "commandProtocolPropertiesList_commandProtocolProperties[0]_nvmeProperties_nvmeofProperties_roceV2Properties_ipv4Data_ipv4OutboundPacketPriority_value",
        "roce_v2_pfc_value",
        _coerce_int,
    ),
]


def _resolve_field_path(data: Any, source_field: str) -> Any:
    value = data
    for part in source_field.split("_"):
        match = INDEXED_PATH_PART.match(part)
        if match is None:
            return None

        key = match.group("key")
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None

        index = match.group("index")
        if index is None:
            continue
        if not isinstance(value, list):
            return None

        resolved_index = int(index)
        if resolved_index >= len(value):
            return None
        value = value[resolved_index]

    return value


def _extract_fields(data: dict[str, Any], field_mappings: list[FieldMapping]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source_field, target_field, transform in field_mappings:
        value = _resolve_field_path(data, source_field)

        if transform and value is not None:
            try:
                value = transform(value)
            except Exception:
                logger.warning(
                    "transform failed for field %r (raw value %r); setting to None",
                    source_field,
                    value,
                )
                value = None

        result[target_field] = value
    return result


def _extract_protocol_payload(entry: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    io_interface_type_data = entry.get("ioInterfaceTypeData")
    if not isinstance(io_interface_type_data, dict):
        return None

    protocol = _normalize_report_protocol(io_interface_type_data.get("interfaceType"))
    if protocol is None:
        return None

    payload_key = "fibre" if protocol == "fibre" else protocol
    payload = io_interface_type_data.get(payload_key)
    if not isinstance(payload, dict):
        return None
    return protocol, payload


def _apply_command_protocol_details(row: dict[str, Any], entry: dict[str, Any]) -> None:
    row.update(_extract_fields(entry, COMMAND_PROTOCOL_COMMON_FIELDS))

    command_provider = row.get("command_provider")
    if command_provider == "provider_infiniband":
        row.update(_extract_fields(entry, COMMAND_PROTOCOL_IB_FIELDS))
        command_ipv4_address = row.get("infiniband_ipv4_address")
        row["command_ipv4_address"] = command_ipv4_address
        row["is_command_ipv4_ready"] = (
            row.get("infiniband_ipv4_config_state") == "configured"
            and bool(command_ipv4_address)
        )
        return

    if command_provider == "provider_roce_v2":
        row.update(_extract_fields(entry, COMMAND_PROTOCOL_ROCE_V2_FIELDS))
        command_ipv4_address = row.get("roce_v2_ipv4_address")
        row["command_ipv4_address"] = command_ipv4_address
        row["is_command_ipv4_ready"] = bool(
            row.get("is_roce_v2_ipv4_enabled") and command_ipv4_address
        )


def _apply_controller_details(
    row: dict[str, Any],
    controller_by_key: dict[str, dict[str, Any]],
) -> None:
    for candidate in (row.get("controller_ref"), row.get("controller_id")):
        if not isinstance(candidate, str) or not candidate:
            continue
        controller = controller_by_key.get(candidate)
        if not controller:
            continue
        row.setdefault("controller_id", controller.get("controller_id"))
        row.setdefault("controller_ref", controller.get("controller_ref"))
        row.setdefault("controller_label", controller.get("controller_label"))
        return


def _controller_lookup(client: Any) -> dict[str, dict[str, Any]]:
    try:
        controllers = client.request("GET", "/controllers") or []
    except RequestError:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for controller in controllers:
        if not isinstance(controller, dict):
            continue
        controller_id = _strip_string(controller.get("id"))
        controller_ref = _strip_string(controller.get("controllerRef")) or controller_id
        physical_location = controller.get("physicalLocation")
        controller_label = None
        if isinstance(physical_location, dict):
            controller_label = _strip_string(physical_location.get("label"))
            if controller_label is not None:
                controller_label = controller_label.lower()
        details = {
            "controller_id": controller_id,
            "controller_ref": controller_ref,
            "controller_label": controller_label,
        }
        for key in (controller_id, controller_ref, controller_label):
            if key:
                result[key] = details
    return result


def _matches_controller(row: dict[str, Any], controller_filter: str) -> bool:
    if controller_filter == "all":
        return True
    candidates = {
        _normalize_filter_value(str(value))
        for value in (
            row.get("controller_label"),
            row.get("controller_ref"),
            row.get("controller_id"),
        )
        if value
    }
    return controller_filter in candidates


def _matches_protocol(row: dict[str, Any], protocol_filter: str) -> bool:
    if protocol_filter == "all":
        return True
    candidates = {
        _normalize_filter_value(str(value))
        for value in (row.get("protocol"), row.get("transport"))
        if value
    }
    return protocol_filter in candidates


def _finalize_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("protocol") == "ib":
        row.setdefault("transport", "ib")
    elif row.get("protocol") == "ethernet":
        row.setdefault("transport", "ethernet")
    elif row.get("protocol") == "fibre":
        row.setdefault("transport", "fibre")
    return {key: value for key, value in row.items() if value is not None}


def hostside_interfaces_report(
    client: Any,
    *,
    controller: str = "all",
    protocol: str = "all",
) -> list[dict[str, Any]]:
    """Return normalized host-side interface rows.

    `protocol` matches either the SANtricity interface protocol (`iscsi`,
    `fibre`, `ib`) or a convenient transport alias such as `ethernet`.
    `controller` accepts `all`, controller labels such as `a` / `b`, or raw
    controller identifiers / references.
    """

    controller_filter = _normalize_filter_value(controller)
    protocol_filter = _normalize_filter_value(protocol)

    controller_by_key = _controller_lookup(client)
    result: list[dict[str, Any]] = []
    for entry in client.interfaces.get_system_hostside_interfaces() or []:
        if not isinstance(entry, dict):
            continue

        payload_info = _extract_protocol_payload(entry)
        if payload_info is None:
            continue
        resolved_protocol, payload = payload_info
        field_mappings = PROTOCOL_FIELD_MAPPINGS.get(resolved_protocol)
        if field_mappings is None:
            continue

        row = _extract_fields(entry, COMMON_FIELDS)
        row.update(_extract_fields(payload, field_mappings))
        _apply_command_protocol_details(row, entry)
        row["protocol"] = resolved_protocol
        _apply_controller_details(row, controller_by_key)
        finalized = _finalize_row(row)

        if not _matches_controller(finalized, controller_filter):
            continue
        if not _matches_protocol(finalized, protocol_filter):
            continue
        result.append(finalized)

    return result


__all__ = ["hostside_interfaces_report"]