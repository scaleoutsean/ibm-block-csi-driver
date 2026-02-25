"""Capability matrix and feature flags for SANtricity releases."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

VersionTuple = tuple[int, int, int]


@dataclass(slots=True)
class CapabilityProfile:
    """Represents the feature surface supported by a SANtricity release family."""

    label: str
    min_version: VersionTuple
    supports_jwt: bool
    mapping_endpoint: str
    legacy_mapping_endpoint: str | None
    clone_endpoint: str
    legacy_clone_endpoint: str | None
    detected_release: str | None = None
    is_future_release: bool = False

    def describe_release(self) -> str:
        return self.detected_release or self.label


_BASE_PROFILES: Sequence[CapabilityProfile] = (
    CapabilityProfile(
        label="11.80",
        min_version=(11, 80, 0),
        supports_jwt=False,
        mapping_endpoint="/volume-mappings",
        legacy_mapping_endpoint="/volume-mappings",
        clone_endpoint="/volume-clones",
        legacy_clone_endpoint="/volume-clones",
    ),
    CapabilityProfile(
        label="11.90",
        min_version=(11, 90, 0),
        supports_jwt=True,
        mapping_endpoint="/volume-mappings",
        legacy_mapping_endpoint="/volume-mappings",
        clone_endpoint="/volume-clones",
        legacy_clone_endpoint="/volume-clones",
    ),
    CapabilityProfile(
        label="12.00",
        min_version=(12, 0, 0),
        supports_jwt=True,
        mapping_endpoint="/v2/volume-mappings",
        legacy_mapping_endpoint="/volume-mappings",
        clone_endpoint="/v2/volume-clones",
        legacy_clone_endpoint="/volume-clones",
    ),
)


def resolve_capabilities(release: str | None) -> CapabilityProfile:
    """Return the capability profile for the requested release (or best-effort default)."""

    version_tuple = _parse_release(release)
    profile = _BASE_PROFILES[-1]
    is_future_release = False

    if version_tuple is not None:
        profile = _BASE_PROFILES[0]
        for candidate in _BASE_PROFILES:
            if version_tuple >= candidate.min_version:
                profile = candidate
        if version_tuple < _BASE_PROFILES[0].min_version:
            warnings.warn(
                "SANtricity releases older than 11.80 receive limited support in this client.",
                stacklevel=2,
            )
        elif version_tuple > _BASE_PROFILES[-1].min_version:
            is_future_release = True
            warnings.warn(
                "Using latest capability profile for an unknown future SANtricity release.",
                stacklevel=2,
            )

    return CapabilityProfile(
        label=profile.label,
        min_version=profile.min_version,
        supports_jwt=profile.supports_jwt,
        mapping_endpoint=profile.mapping_endpoint,
        legacy_mapping_endpoint=profile.legacy_mapping_endpoint,
        clone_endpoint=profile.clone_endpoint,
        legacy_clone_endpoint=profile.legacy_clone_endpoint,
        detected_release=release or profile.label,
        is_future_release=is_future_release,
    )


def _parse_release(release: str | None) -> VersionTuple | None:
    if not release:
        return None
    parts = release.split(".")
    version: list[int] = []
    for part in parts[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        version.append(int(digits) if digits else 0)
    while len(version) < 3:
        version.append(0)
    return tuple(version)  # type: ignore[return-value]


__all__ = ["CapabilityProfile", "resolve_capabilities"]
