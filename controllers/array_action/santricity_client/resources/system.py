"""System metadata helpers for firmware discovery."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..exceptions import RequestError
from .base import ResourceBase


class SystemResource(ResourceBase):
    """Expose utility endpoints for release detection."""

    def get_info(self) -> dict[str, Any]:
        """Return storage-system metadata (including chassisSerialNumber when available)."""

        payload = self._client.request("GET", "/storage-systems", system_scope=False)
        if isinstance(payload, dict):
            return payload
        if not isinstance(payload, list):
            raise RequestError("Unexpected /storage-systems payload shape; expected list or object.")

        system_id = self._client.system_id
        selected = self._select_system_payload(payload, system_id)
        if selected is None:
            raise RequestError(
                f"Unable to find storage-system metadata for system id '{system_id}'."
            )
        return selected

    def build_info(self) -> dict[str, Any]:
        """Return the /utils/buildinfo payload."""

        return self._client.request("GET", self._buildinfo_url(), system_scope=False)

    def firmware_versions(self) -> dict[str, Any]:
        """Return the embedded firmware code versions."""

        return self._get(
            "/firmware/embedded-firmware/1/versions",
            system_scope=False,
        )

    def release_summary(self) -> dict[str, Any]:
        """Summarize the best-known software version across firmware endpoints."""

        summary: dict[str, Any] = {
            "version": None,
            "source": None,
            "bundleDisplay": None,
            "management": None,
            "symbolApi": None,
            "symbolVersion": None,
            "errors": [],
        }
        errors: list[str] = []

        try:
            firmware = self.firmware_versions()
        except RequestError as exc:
            errors.append(f"firmware versions: {exc}")
        else:
            summary["bundleDisplay"] = self._extract_code_version(firmware, "bundleDisplay")
            summary["management"] = self._extract_code_version(firmware, "management")

        try:
            build_info = self.build_info()
        except RequestError as exc:
            errors.append(f"buildinfo: {exc}")
        else:
            summary["symbolApi"] = self._extract_component(build_info, "symbolapi")
            summary["symbolVersion"] = self._extract_component(build_info, "symbolversion")

        summary["version"], summary["source"] = self._select_version(summary)
        summary["errors"] = errors
        return summary

    def _buildinfo_url(self) -> str:
        return f"{self._devmgr_root()}/utils/buildinfo"

    def _devmgr_root(self) -> str:
        base_url = self._client.config.base_url
        parsed = urlsplit(base_url)
        host_root = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        path = parsed.path or ""
        marker = path.find("/devmgr")
        if marker != -1:
            prefix = path[:marker] + "/devmgr"
        else:
            prefix = "/devmgr"
        normalized = prefix.rstrip("/")
        return f"{host_root}{normalized}" if normalized else host_root

    @staticmethod
    def _extract_code_version(payload: dict[str, Any], module_name: str) -> str | None:
        code_versions = payload.get("codeVersions")
        if not isinstance(code_versions, list):
            return None
        target = module_name.lower()
        for entry in code_versions:
            if not isinstance(entry, dict):
                continue
            module = entry.get("codeModule")
            version = entry.get("versionString")
            if isinstance(module, str) and module.lower() == target and isinstance(version, str):
                cleaned = version.strip()
                if cleaned:
                    return cleaned
        return None

    @staticmethod
    def _extract_component(payload: dict[str, Any], component_name: str) -> str | None:
        components = payload.get("components")
        if not isinstance(components, list):
            return None
        target = component_name.lower()
        for entry in components:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            version = entry.get("version")
            if isinstance(name, str) and name.lower() == target and isinstance(version, str):
                cleaned = version.strip()
                if cleaned:
                    return cleaned
        return None

    @staticmethod
    def _select_version(summary: dict[str, Any]) -> tuple[str | None, str | None]:
        priorities = ("bundleDisplay", "management", "symbolApi", "symbolVersion")
        for key in priorities:
            value = summary.get(key)
            if isinstance(value, str) and value.strip():
                return value, key
        return None, None

    @staticmethod
    def _select_system_payload(
        payload: list[dict[str, Any] | Any], system_id: str
    ) -> dict[str, Any] | None:
        normalized = system_id.strip()
        first_entry: dict[str, Any] | None = None
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            if first_entry is None:
                first_entry = entry
            entry_id = entry.get("wwn") or entry.get("id")
            if isinstance(entry_id, str) and entry_id.strip() == normalized:
                return entry
        return first_entry


__all__ = ["SystemResource"]
