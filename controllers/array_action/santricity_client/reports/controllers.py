"""Controller report definitions and helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .interfaces_report import hostside_interfaces_report

FieldTransform = Callable[[Any], Any]
FieldMapping = tuple[str, str, FieldTransform | None]


def _strip_string(value: Any) -> str | None:
  if isinstance(value, str):
    cleaned = value.strip()
    return cleaned or None
  return None


def _lower_string(value: Any) -> str | None:
  cleaned = _strip_string(value)
  return cleaned.lower() if cleaned else None


def _coerce_int(value: Any) -> int | None:
  if value is None:
    return None
  return int(value)


def _normalize_filter_value(value: str) -> str:
  normalized = value.strip().lower()
  aliases = {"*": "all"}
  return aliases.get(normalized, normalized)

CONTROLLERS: list[FieldMapping] = [
  ("active", "active", None),
  ("boardSubmodelID", "board_submodel_id", _strip_string),
  ("bootTime", "boot_time", _strip_string),
  ("cacheMemorySize", "cache_memory_size_bytes", _coerce_int),
  ("controllerErrorMode", "controller_error_mode", _strip_string),
  ("controllerRef", "controller_ref", _strip_string),
  ("ctrlIocDumpData", "ctrl_ioc_dump_data", None),
  ("flashCacheMemorySize", "flash_cache_memory_size_bytes", _coerce_int),
  ("hasTrayIdentityIndicator", "has_tray_identity_indicator", None),
  ("id", "id", _strip_string),
  ("locateInProgress", "is_locate_in_progress", None),
  ("manufacturer", "manufacturer", _strip_string),
  ("modelName", "model_name", _strip_string),
  ("partNumber", "part_number", _strip_string),
  ("physicalCacheMemorySize", "physical_cache_memory_size_bytes", _coerce_int),
  ("physicalLocation_label", "physical_location_label", _lower_string),
  ("quiesced", "is_quiesced", None),
  ("readyToRemove", "is_ready_to_remove", None),
  ("serialNumber", "serial_number", _strip_string),
  ("status", "status", _strip_string),
]


def _extract_fields(data: dict[str, Any], field_mappings: list[FieldMapping]) -> dict[str, Any]:
  result: dict[str, Any] = {}
  for source_field, target_field, transform in field_mappings:
    value: Any = data
    for part in source_field.split("_"):
      if isinstance(value, dict) and part in value:
        value = value[part]
      else:
        value = None
        break

    if transform and value is not None:
      value = transform(value)

    result[target_field] = value
  return result


def _matches_controller(row: dict[str, Any], controller_filter: str) -> bool:
  if controller_filter == "all":
    return True
  candidates = {
    _normalize_filter_value(str(value))
    for value in (
      row.get("physical_location_label"),
      row.get("controller_ref"),
      row.get("id"),
    )
    if value
  }
  return controller_filter in candidates


def _group_hostside_interfaces(
  rows: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
  grouped: dict[str, list[dict[str, Any]]] = {}
  counts: dict[str, int] = {}
  for row in rows:
    keys = {
      str(value)
      for value in (
        row.get("controller_ref"),
        row.get("controller_id"),
        row.get("controller_label"),
      )
      if value
    }
    for key in keys:
      grouped.setdefault(key, []).append(row)
      counts[key] = counts.get(key, 0) + 1
  return grouped, counts


def _finalize_row(row: dict[str, Any]) -> dict[str, Any]:
  return {key: value for key, value in row.items() if value is not None}


def controllers_report(
  client: Any,
  *,
  controller: str = "all",
  protocol: str = "all",
  include_hostside_interfaces: bool = True,
) -> list[dict[str, Any]]:
  """Return normalized controller rows with optional host-side interface details."""

  controller_filter = _normalize_filter_value(controller)
  controllers = client.request("GET", "/controllers") or []

  hostside_rows: list[dict[str, Any]] = []
  if include_hostside_interfaces:
    hostside_rows = hostside_interfaces_report(
      client,
      controller="all",
      protocol=protocol,
    )
  grouped_hostside, hostside_counts = _group_hostside_interfaces(hostside_rows)

  result: list[dict[str, Any]] = []
  for controller_obj in controllers:
    if not isinstance(controller_obj, dict):
      continue
    row = _extract_fields(controller_obj, CONTROLLERS)
    row.setdefault("controller_ref", row.get("id"))

    if not _matches_controller(row, controller_filter):
      continue

    if include_hostside_interfaces:
      key_candidates = [
        str(value)
        for value in (
          row.get("controller_ref"),
          row.get("id"),
          row.get("physical_location_label"),
        )
        if value
      ]
      hostside_items: list[dict[str, Any]] = []
      for key in key_candidates:
        hostside_items = grouped_hostside.get(key, [])
        if hostside_items:
          row["hostside_interface_count"] = hostside_counts.get(key, len(hostside_items))
          row["hostside_interfaces"] = hostside_items
          break
      if not hostside_items:
        row["hostside_interface_count"] = 0
        row["hostside_interfaces"] = []

    result.append(_finalize_row(row))

  return result

__all__ = ["CONTROLLERS", "controllers_report"]