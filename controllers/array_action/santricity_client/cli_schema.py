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
}
