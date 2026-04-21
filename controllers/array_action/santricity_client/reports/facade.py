"""Facade for fixed-shape report helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .controllers import controllers_report
from .interfaces_report import hostside_interfaces_report
from .mappings import mappings_report

if TYPE_CHECKING:  # pragma: no cover - import-time guard
    from ..client import SANtricityClient


class ReportsFacade:
    """Expose fixed-shape, consumer-friendly report builders."""

    def __init__(self, client: SANtricityClient) -> None:
        self._client = client

    def mappings(self) -> list[dict[str, Any]]:
        return mappings_report(self._client)

    def interfaces(
        self,
        *,
        controller: str = "all",
        protocol: str = "all",
    ) -> list[dict[str, Any]]:
        return hostside_interfaces_report(
            self._client,
            controller=controller,
            protocol=protocol,
        )

    def controllers(
        self,
        *,
        controller: str = "all",
        protocol: str = "all",
        include_hostside_interfaces: bool = True,
    ) -> list[dict[str, Any]]:
        return controllers_report(
            self._client,
            controller=controller,
            protocol=protocol,
            include_hostside_interfaces=include_hostside_interfaces,
        )