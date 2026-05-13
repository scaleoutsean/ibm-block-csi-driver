"""Schema describing important fields for CLI table rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

Row = Mapping[str, Any]
ValueExtractor = Callable[[Row], Any]
ValueFormatter = Callable[[Any], str]
SortKey = Callable[[Row], Any]


@dataclass(frozen=True)
class Column:
    """Describe how to pull and format a column for Rich tables."""

    header: str
    keys: tuple[str, ...] = ()
    extractor: ValueExtractor | None = None
    formatter: ValueFormatter | None = None
    justify: str = "left"

    def render(self, row: Row) -> str:
        value: Any | None = None
        if self.keys:
            for key in self.keys:
                if key in row:
                    value = row.get(key)
                    if value is not None:
                        break
        if value is None and self.extractor:
            value = self.extractor(row)
        if value is None:
            return ""
        if self.formatter:
            formatted = self.formatter(value)
            return "" if formatted is None else str(formatted)
        return str(value)


@dataclass(frozen=True)
class TableView:
    """Describe a Rich table for a CLI command."""

    title: str
    columns: tuple[Column, ...]
    sort_key: SortKey | None = None


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:  # pragma: no cover - defensive
            return None
    return None


def _bytes_formatter(*, precision: int = 2) -> ValueFormatter:
    def _formatter(value: Any) -> str:
        number = _coerce_number(value)
        if number is None:
            return ""
        gib_value = number / (1024**3)
        return f"{gib_value:.{precision}f}"

    return _formatter


def _bool_formatter(value: Any) -> str:
    if value is None:
        return ""
    return "Yes" if bool(value) else "No"


def _list_formatter(*, max_chars: int = 16, sep: str = ", ") -> ValueFormatter:
    def _formatter(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            s = sep.join(str(v) for v in value)
        else:
            s = str(value)
        return s if len(s) <= max_chars else s[: max_chars - 1] + "…"

    return _formatter


def _truncate_formatter(*, max_chars: int = 18) -> ValueFormatter:
    def _formatter(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    return _formatter


def _first_present(*keys: str) -> ValueExtractor:
    def _extractor(row: Row) -> Any:
        for key in keys:
            if key in row:
                return row.get(key)
        return None

    return _extractor


def _supported_block_sizes(row: Row) -> Any:
    # Try several possible keys and normalize to a list or single value
    candidates = (
        "isBlockSizeSupported",
        "supportedBlockSizes",
        "supportedSectorSizes",
        "blockSizesSupported",
        "blockSizeSupported",
        "blkSizeSupported",
    )
    for key in candidates:
        if key in row:
            val = row.get(key)
            if val is None:
                return None
            if isinstance(val, Mapping):
                sizes = [str(k) for k, v in val.items() if v]
                return sizes
            if isinstance(val, str):
                parts = [p.strip() for p in val.split(",") if p.strip()]
                return parts
            if isinstance(val, (list, tuple)):
                return [str(x) for x in val]
            if isinstance(val, bool):
                return "Yes" if val else "No"
            return [str(val)]
    return None


def _mapping_target(row: Row) -> str:
    for key in (
        "targetLabel",
        "hostGroup",
        "hostLabel",
        "targetName",
        "hostGroupLabel",
        "clusterName",
    ):
        candidate = row.get(key)
        if candidate:
            return str(candidate)
    # fall back to identifiers if no name-like field is available
    for key in ("targetId", "clusterRef", "hostRef", "mapRef", "ssid"):
        candidate = row.get(key)
        if candidate:
            return str(candidate)
    return "-"


def _volume_pool(row: Row) -> str:
    for key in ("poolId", "storagePoolId", "volumeGroupRef"):
        candidate = row.get(key)
        if candidate:
            return str(candidate)
    return ""


def _sort_label(row: Row) -> str:
    return str(row.get("label") or row.get("name") or "").lower()


def _hostside_interfaces(row: Row) -> list[Row]:
    value = row.get("hostside_interfaces")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _hostside_ready_summary(row: Row) -> str:
    interfaces = _hostside_interfaces(row)
    if not interfaces:
        return ""
    ready_count = sum(1 for item in interfaces if item.get("is_command_ipv4_ready") is True)
    return f"{ready_count}/{len(interfaces)}"


def _hostside_protocol_summary(row: Row) -> str:
    interfaces = _hostside_interfaces(row)
    if not interfaces:
        return ""
    values = sorted(
        {
            str(item.get("command_provider") or item.get("protocol") or item.get("transport"))
            for item in interfaces
            if item.get("command_provider") or item.get("protocol") or item.get("transport")
        }
    )
    return ", ".join(values)


def _raid_level(row: Row) -> str:
    """Return a best-effort RAID level for a pool row.

    Preference order:
    - row['raidLevel'] if present
    - row['extents'][0]['raidLevel'] if extents is non-empty and first extent is a mapping
    - row['type']
    - empty string
    """
    rl = row.get("raidLevel")
    if rl is not None and rl != "":
        return str(rl)

    extents = row.get("extents")
    if isinstance(extents, (list, tuple)) and extents:
        first = extents[0]
        if isinstance(first, Mapping):
            val = first.get("raidLevel")
            if val is not None and val != "":
                return str(val)

    t = row.get("type")
    if t is not None:
        return str(t)

    return ""


# Use this pattern to add additional columns from top level keys as needed
# Column("Read Cache", extractor=lambda r: r.get("cache", {}).get("readCacheActive"),
#        formatter=_bool_formatter, justify="center")

CLI_TABLE_VIEWS: dict[str, TableView] = {
    "pools.list": TableView(
        title="Storage Pools",
        columns=(
            Column("Label", keys=("label", "name")),
            Column("Pool Ref", keys=("poolRef", "id", "storagePoolId")),
            Column("RAID Lvl", extractor=_raid_level),
            Column(
                "Capacity (GiB)",
                keys=("totalRaidedSpace", "capacity"),
                formatter=_bytes_formatter(precision=1),
                justify="right",
            ),
            Column(
                "Free (GiB)",
                keys=("freeSpace", "availableSpace"),
                formatter=_bytes_formatter(precision=1),
                justify="right",
            ),
            Column(
                "Supported sector sizes",
                extractor=_supported_block_sizes,
                formatter=_list_formatter(max_chars=16),
                justify="left",
            ),
            Column("Status", keys=("status", "state")),
        ),
        sort_key=_sort_label,
    ),
    "volumes.list": TableView(
        title="Volumes",
        columns=(
            Column("Name", keys=("name", "label")),
            Column("Volume Ref", keys=("volumeRef", "id")),
            Column("Pool Ref", keys=("volumeGroupRef",)),
            Column(
                "Cap (GiB)",
                keys=("capacity", "reportedSize", "currentVolumeSize"),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
            Column(
                "Cache (r)",
                extractor=lambda r: r.get("cache", {}).get("readCacheEnable"),
                formatter=_bool_formatter,
                justify="center",
            ),
            Column(
                "Cache (w)",
                extractor=lambda r: r.get("cache", {}).get("writeCacheEnable"),
                formatter=_bool_formatter,
                justify="center",
            ),
            Column("Status", keys=("status", "state")),
        ),
        sort_key=lambda row: str(row.get("name") or row.get("label") or "").lower(),
    ),
    "mappings.list": TableView(
        title="Volume Mappings",
        columns=(
            Column("Mapping Ref", keys=("lunMappingRef", "mappingRef", "id")),
            Column(
                "Volume",
                keys=(
                    "mappableObjectName",
                    "name",
                    "label",
                    "volumeName",
                    "volumeRef",
                    "mappableObjectId",
                ),
            ),
            Column("Target", extractor=_mapping_target),
            Column("LUN", keys=("lun",), justify="right"),
        ),
        sort_key=lambda row: str(row.get("mappingRef") or row.get("id") or ""),
    ),
    "snapshots.list-groups": TableView(
        title="Snapshot Groups",
        columns=(
            Column("Name", keys=("name", "label")),
            Column("Pit Group Ref", keys=("pitGroupRef", "id")),
            Column("Sched Owned", keys=("isScheduleOwned",), formatter=_bool_formatter, justify="center"),
            Column("Sched Count", keys=("scheduleCount",), justify="right"),
            Column("Base Volume", keys=("baseVolume",)),
            Column("Snapshots", keys=("snapshotCount",), justify="right"),
            Column(
                "Repo Cap (GiB)",
                keys=("repositoryCapacity",),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
            Column("CG", keys=("consistencyGroup",), formatter=_bool_formatter, justify="center"),
            Column("Status", keys=("status",)),
        ),
        sort_key=_sort_label,
    ),
    "snapshots.list-images": TableView(
        title="Snapshot Images",
        columns=(
            Column("Snapshot Group", keys=("snapshotGroupName",)),
            Column("Pit Ref", keys=("pitRef", "id")),
            Column("Seq #", keys=("pitSequenceNumber",), justify="right"),
            Column("Timestamp", keys=("pitTimestamp",), justify="right"),
            Column("Created By", keys=("creationMethod",)),
            Column("Repo Use %", keys=("repositoryCapacityUtilization",), justify="right"),
            Column("Status", keys=("status",)),
        ),
    ),
    "snapshots.list-volumes": TableView(
        title="Snapshot Volumes",
        columns=(
            Column("Name", keys=("name", "label")),
            Column("View Ref", keys=("viewRef", "id")),
            Column("Base Vol", keys=("baseVol",)),
            Column("Access", keys=("accessMode",)),
            Column(
                "Repo Cap (GiB)",
                keys=("repositoryCapacity",),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
            Column("Status", keys=("status",)),
        ),
        sort_key=_sort_label,
    ),
    "snapshots.list-repo-groups": TableView(
        title="Repository Volumes (Concat)",
        columns=(
            Column("Concat Vol Ref", keys=("concatVolRef", "id")),
            Column("Base Object ID", keys=("baseObjectId",)),
            Column("Base Object Type", keys=("baseObjectType",)),
            Column("Members", keys=("memberCount",), justify="right"),
            Column(
                "Aggregate Cap (GiB)",
                keys=("aggregateCapacity",),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
            Column("Status", keys=("status",)),
        ),
    ),
    "snapshots.list-repo-volumes": TableView(
        title="Repository-related Volumes",
        columns=(
            Column("Name", keys=("label", "name")),
            Column("Volume Ref", keys=("volumeRef", "id")),
            Column("Use", keys=("volumeUse",)),
            Column("Mapped", keys=("mapped",), formatter=_bool_formatter, justify="center"),
            Column(
                "Cap (GiB)",
                keys=("totalSizeInBytes", "capacity", "reportedSize", "currentVolumeSize"),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
            Column("Pool Ref", keys=("volumeGroupRef",)),
            Column("Status", keys=("status", "state")),
        ),
        sort_key=lambda row: str(row.get("label") or row.get("name") or "").lower(),
    ),
    "snapshots.list-group-util": TableView(
        title="Snapshot Group Repository Utilization",
        columns=(
            Column("Group", keys=("snapshotGroupName", "groupRef")),
            Column("Group Ref", keys=("groupRef",)),
            Column("Sched Owned", keys=("isScheduleOwned",), formatter=_bool_formatter, justify="center"),
            Column("Sched Count", keys=("scheduleCount",), justify="right"),
            Column(
                "Used (GiB)",
                keys=("pitGroupBytesUsed",),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
            Column(
                "Available (GiB)",
                keys=("pitGroupBytesAvailable",),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
        ),
    ),
    "snapshots.list-volume-util": TableView(
        title="Snapshot Volume Repository Utilization",
        columns=(
            Column("View Ref", keys=("viewRef",)),
            Column(
                "Used (GiB)",
                keys=("viewBytesUsed",),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
            Column(
                "Available (GiB)",
                keys=("viewBytesAvailable",),
                formatter=_bytes_formatter(precision=2),
                justify="right",
            ),
        ),
    ),
    "snapshots.list-cg-members": TableView(
        title="Consistency Group Member Volumes",
        columns=(
            Column("Volume Name", keys=("volumeName", "label")),
            Column("Volume Ref", keys=("volumeRef",)),
            Column("CG ID", keys=("consistencyGroupId",)),
            Column("Pit Group Ref", keys=("pitGroupRef",)),
        ),
        sort_key=lambda row: str(row.get("volumeName") or row.get("label") or "").lower(),
    ),
    "snapshots.list-schedules": TableView(
        title="Snapshot Schedules",
        columns=(
            Column("Snapshot Group", keys=("snapshotGroupName",)),
            Column("Sched Ref", keys=("schedRef", "id")),
            Column("Status", keys=("scheduleStatus",)),
            Column("Next Run", keys=("nextRunTime",), justify="right"),
        ),
        sort_key=lambda row: str(row.get("snapshotGroupName") or "").lower(),
    ),
    "hosts.membership": TableView(
        title="Host Membership",
        columns=(
            Column("Host", keys=("hostLabel", "label")),
            Column("Host Ref", keys=("hostRef",)),
            Column("Group", keys=("hostGroup", "clusterRef")),
            Column(
                "In Group",
                keys=("belongsToGroup",),
                formatter=_bool_formatter,
                justify="center",
            ),
        ),
        sort_key=lambda row: str(row.get("hostLabel") or row.get("label") or "").lower(),
    ),
    "reports.interfaces": TableView(
        title="Host-side Interfaces",
        columns=(
            Column("Ctrl", keys=("controller_label", "controller_id", "controller_ref")),
            Column("Protocol", keys=("protocol",)),
            Column("Interface", keys=("interface_id",), formatter=_truncate_formatter(max_chars=18)),
            Column("Channel", keys=("channel",), justify="right"),
            Column("Transport", keys=("transport",)),
            Column("Addr", keys=("ipv4_address", "infiniband_ipv4_address", "roce_v2_ipv4_address", "node_name")),
            Column("Cmd IPv4", keys=("command_ipv4_address",)),
            Column("NVMe Ready", keys=("is_command_ipv4_ready",), formatter=_bool_formatter, justify="center"),
            Column("Provider", keys=("command_provider",), formatter=_truncate_formatter(max_chars=18)),
        ),
        sort_key=lambda row: (
            str(row.get("controller_label") or row.get("controller_id") or row.get("controller_ref") or "").lower(),
            str(row.get("protocol") or "").lower(),
            str(row.get("channel") or ""),
            str(row.get("interface_id") or "").lower(),
        ),
    ),
    "reports.controllers": TableView(
        title="Controllers",
        columns=(
            Column("Ctrl", keys=("physical_location_label", "id", "controller_ref")),
            Column("Model", keys=("model_name",), formatter=_truncate_formatter(max_chars=18)),
            Column("Status", keys=("status",)),
            Column("Ifaces", keys=("hostside_interface_count",), justify="right"),
            Column("NVMe Ready", extractor=_hostside_ready_summary, justify="center"),
            Column("Protocols", extractor=_hostside_protocol_summary, formatter=_truncate_formatter(max_chars=22)),
        ),
        sort_key=lambda row: str(row.get("physical_location_label") or row.get("id") or row.get("controller_ref") or "").lower(),
    ),
}
