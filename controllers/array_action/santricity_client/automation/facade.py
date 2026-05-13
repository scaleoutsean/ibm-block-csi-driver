"""Facade for higher-level automation workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .snapshots import SnapshotsAutomation

if TYPE_CHECKING:  # pragma: no cover - import-time guard
    from ..client import SANtricityClient


class AutomationFacade:
    """Expose workflow-oriented helpers that sit above raw resources."""

    def __init__(self, client: SANtricityClient) -> None:
        self.snapshots = SnapshotsAutomation(client)