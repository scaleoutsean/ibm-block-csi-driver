"""Configuration helpers for SANtricity client."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass

SYMBOL_LEGACY_PATH = "symbol"


@dataclass(slots=True)
class ClientConfig:
    """Typed configuration for `SANtricityClient`."""

    base_url: str
    verify_ssl: bool | str = True
    timeout: float = 30.0
    default_headers: Mapping[str, str] | None = None
    query_defaults: Mapping[str, str] | None = None
    release_version: str | None = None
    system_id: str | None = None

    def resolved_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.default_headers:
            headers.update(self.default_headers)
        return headers

    def resolved_query(self) -> dict[str, str]:
        return dict(self.query_defaults or {})


@dataclass(slots=True)
class RequestParams:
    """Bundle together prepared request details."""

    method: str
    path: str
    params: Mapping[str, str] | None = None
    headers: MutableMapping[str, str] | None = None
    payload: Mapping[str, object] | None = None
