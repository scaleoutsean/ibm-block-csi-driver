"""Common helpers for resource wrappers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..exceptions import RequestError

if TYPE_CHECKING:  # pragma: no cover - import-time guard
    from ..client import SANtricityClient


class ResourceBase:
    """Provide shared helpers for resource modules."""

    def __init__(self, client: SANtricityClient) -> None:
        self._client = client

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        system_scope: bool = True,
    ) -> Any:
        return self._request_with_fallback("GET", path, params=params, system_scope=system_scope)

    def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        system_scope: bool = True,
    ) -> Any:
        return self._request_with_fallback("POST", path, payload=payload, system_scope=system_scope)

    def _delete(self, path: str, *, system_scope: bool = True) -> Any:
        return self._client.request("DELETE", path, system_scope=system_scope)

    def _symbol_request(
        self,
        symbol_path: str,
        *,
        method: str = "POST",
        params: Mapping[str, str] | None = None,
        payload_data: Any | None = None,
        expect_json: bool = False,
    ) -> Any:
        from ..config import SYMBOL_LEGACY_PATH

        full_path = f"/{SYMBOL_LEGACY_PATH}/{symbol_path.lstrip('/')}"
        return self._client.request(
            method,
            full_path,
            params=params,
            data_payload=payload_data,
            expect_json=expect_json,
        )

    def _request_with_fallback(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
        fallback_path: str | None = None,
        recoverable_statuses: tuple[int, ...] = (404, 405),
        system_scope: bool = True,
    ) -> Any:
        try:
            return self._client.request(
                method,
                path,
                params=params,
                json_payload=payload,
                system_scope=system_scope,
            )
        except RequestError as exc:
            can_retry = (
                fallback_path and fallback_path != path and exc.status_code in recoverable_statuses
            )
            if can_retry:
                return self._client.request(
                    method,
                    fallback_path,
                    params=params,
                    json_payload=payload,
                    system_scope=system_scope,
                )
            raise
