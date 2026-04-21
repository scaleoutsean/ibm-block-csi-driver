"""Snapshot workflow helpers that orchestrate multiple raw API calls."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import-time guard
    from ..client import SANtricityClient


class SnapshotsAutomation:
    """Namespace for higher-level snapshot automation workflows."""

    def __init__(self, client: SANtricityClient) -> None:
        self._client = client