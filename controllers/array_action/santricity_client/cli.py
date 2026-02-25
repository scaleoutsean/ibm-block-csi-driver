"""Command-line interface for interacting with SANtricity arrays."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import typer

try:  # pragma: no cover - exercised in runtime environments
    from rich import box
    from rich.console import Console
    from rich.table import Table
except ImportError as exc:  # pragma: no cover - optional dependency guard
    raise RuntimeError(
        "The CLI requires Rich for table rendering. Install the CLI extras via "
        "'pip install santricity-python[cli]' to enable this command."
    ) from exc

from . import SANtricityClient
from .auth.basic import BasicAuth
from .auth.jwt import JWTAuth
from .cli_schema import CLI_TABLE_VIEWS, TableView
from .exceptions import AuthenticationError, RequestError, ResolutionError

app = typer.Typer(help="SANtricity storage management CLI.", no_args_is_help=True)

hosts_app = typer.Typer(help="Host operations.")
pools_app = typer.Typer(help="Pool operations.")
volumes_app = typer.Typer(help="Volume operations.")
mappings_app = typer.Typer(help="Volume mapping operations.")
system_app = typer.Typer(help="System metadata operations.")
app.add_typer(hosts_app, name="hosts")
app.add_typer(pools_app, name="pools")
app.add_typer(volumes_app, name="volumes")
app.add_typer(mappings_app, name="mappings")
app.add_typer(system_app, name="system")


def _build_client(
    base_url: str,
    auth: str,
    username: str | None,
    password: str | None,
    token: str | None,
    verify_ssl: bool,
    cert_path: Path | None,
    timeout: float,
    release_version: str | None,
    system_id: str | None,
) -> SANtricityClient:
    auth = auth.lower()
    if auth not in {"basic", "jwt"}:
        raise typer.BadParameter("--auth must be either 'basic' or 'jwt'.")

    if auth == "jwt":
        if not token:
            raise typer.BadParameter("--token is required when --auth jwt is selected.")
        strategy = JWTAuth(token=token)
    else:
        if not username or not password:
            raise typer.BadParameter("--username and --password are required for basic auth.")
        strategy = BasicAuth(username=username, password=password)

    verify_target: bool | str
    if cert_path:
        expanded_cert = cert_path.expanduser()
        if not expanded_cert.exists():
            raise typer.BadParameter("Certificate file not found for --cert option.")
        if not verify_ssl:
            typer.secho("Cannot combine --cert with --no-verify.", err=True, fg=typer.colors.RED)
            raise typer.BadParameter("Cannot combine --cert with --no-verify.")
        verify_target = str(expanded_cert)
    else:
        verify_target = verify_ssl

    return SANtricityClient(
        base_url=base_url,
        auth_strategy=strategy,
        verify_ssl=verify_target,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    )


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2))


console = Console(force_terminal=False, color_system=None)


def _render_rich_table(view: TableView, rows: Sequence[Mapping[str, Any]]) -> None:
    table = Table(
        title=view.title,
        box=box.SIMPLE,
        show_lines=False,
        header_style="bold cyan",
    )
    for column in view.columns:
        table.add_column(column.header, justify=column.justify)
    ordered_rows = list(rows)
    if view.sort_key:
        ordered_rows.sort(key=view.sort_key)
    for row in ordered_rows:
        table.add_row(*(column.render(row) for column in view.columns))
    console.print(table)


def _present_output(payload: Any, *, view_id: str | None, json_output: bool) -> None:
    if json_output or view_id is None:
        _echo_json(payload)
        return
    view = CLI_TABLE_VIEWS.get(view_id)
    if not view:
        _echo_json(payload)
        return
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        _echo_json(payload)
        return
    rows: list[Mapping[str, Any]] = []
    for item in payload:
        if isinstance(item, Mapping):
            rows.append(item)
    if not rows:
        _echo_json(payload)
        return
    _render_rich_table(view, rows)


def _handle_request_error(exc: RequestError) -> None:
    message = f"Request failed (status {exc.status_code}): {exc}"
    if exc.details:
        message += f"\nDetails: {exc.details}"
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1)


def _shared_options() -> dict[str, Any]:  # pragma: no cover - helper indirection
    # Respect SANTRICITY_VERIFY_SSL environment variable when present.
    # Accept common truthy/falsey representations (1/0, true/false, yes/no).
    env_verify = os.getenv("SANTRICITY_VERIFY_SSL")
    if env_verify is None:
        default_verify = True
    else:
        low = env_verify.strip().lower()
        if low in {"0", "false", "no", "off"}:
            default_verify = False
        else:
            default_verify = True

    return {
        "base_url": typer.Option(
            ..., "--base-url", envvar="SANTRICITY_BASE_URL", help="SANtricity API base URL."
        ),
        "username": typer.Option(
            None,
            "--username",
            "-u",
            envvar="SANTRICITY_USERNAME",
            help="Array username for basic auth.",
        ),
        "password": typer.Option(
            None,
            "--password",
            "-p",
            envvar="SANTRICITY_PASSWORD",
            help="Array password for basic auth.",
            hide_input=True,
        ),
        "token": typer.Option(
            None,
            "--token",
            envvar="SANTRICITY_TOKEN",
            help="JWT bearer token when --auth=jwt.",
        ),
        "auth": typer.Option(
            "basic",
            "--auth",
            "-a",
            case_sensitive=False,
            help="Authentication strategy to use (basic or jwt).",
        ),
        "verify_ssl": typer.Option(
            default_verify,
            "--verify/--no-verify",
            envvar="SANTRICITY_VERIFY_SSL",
            help="Enable or disable TLS certificate verification.",
            show_default=True,
        ),
        "cert_path": typer.Option(
            None,
            "--cert",
            envvar="SANTRICITY_CA_CERT",
            help="Path to a custom CA bundle for TLS verification.",
        ),
        "timeout": typer.Option(30.0, help="Request timeout (seconds).", show_default=True),
        "release_version": typer.Option(
            None,
            "--release-version",
            envvar="SANTRICITY_RELEASE",
            help="Optional SANtricity release identifier (e.g., 11.94).",
        ),
        "system_id": typer.Option(
            None,
            "--system-id",
            envvar="SANTRICITY_SYSTEM_ID",
            help="Optional storage-system WWN to scope API requests.",
        ),
        "output_json": typer.Option(
            False,
            "--json",
            "-j",
            help="Return raw JSON instead of rendering a table.",
        ),
    }


_SHARED_OPTIONS = _shared_options()


def _volume_create_options() -> dict[str, Any]:  # pragma: no cover - helper indirection
    return {
        "pool_id": typer.Option(..., "--pool-id", help="Target storage pool identifier."),
        "name": typer.Option(..., "--name", help="Volume label."),
        "size": typer.Option(..., "--size", help="Volume size value (e.g., 10)."),
        "size_unit": typer.Option(
            "gb",
            "--size-unit",
            help="Unit for size (bytes, kb, mb, gb, tb).",
            show_default=True,
        ),
        "raid_level": typer.Option(
            None,
            "--raid-level",
            help="Optional RAID level override.",
        ),
        "block_size": typer.Option(
            None,
            "--block-size",
            help="Optional block size in bytes.",
        ),
        "data_assurance": typer.Option(
            False,
            "--data-assurance/--no-data-assurance",
            help="Enable PI/data assurance for the volume.",
            show_default=True,
        ),
        "tag": typer.Option(
            [],
            "--tag",
            help="Metadata tag in key=value form.",
            show_default=False,
        ),
        "payload_file": typer.Option(
            None,
            "--payload",
            help="Path to JSON payload template (overrides other volume options).",
        ),
        "extras": typer.Option(
            None,
            "--extras",
            help=(
                "Comma-separated key=value pairs to include in the payload "
                "(e.g. enableCache=True,someVar=1)."
            ),
            show_default=False,
        ),
    }


_VOLUME_CREATE_OPTIONS = _volume_create_options()


def _collect_duplicate_volume_names(volumes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for volume in volumes:
        label = (volume.get("name") or volume.get("label") or "").strip()
        if not label:
            continue
        buckets.setdefault(label, []).append(volume)
    duplicates: list[dict[str, Any]] = []
    for label, items in buckets.items():
        if len(items) <= 1:
            continue
        duplicates.append(
            {
                "name": label,
                "count": len(items),
                "volumeRefs": [item.get("volumeRef") for item in items],
            }
        )
    return duplicates


def _ensure_volume_name_is_unique(client: SANtricityClient, volume_name: str) -> None:
    try:
        volumes = client.volumes.list()
    except RequestError as exc:
        _handle_request_error(exc)
        return
    for volume in volumes:
        label = volume.get("name") or volume.get("label")
        if label == volume_name:
            volume_ref = volume.get("volumeRef", "unknown")
            typer.secho(
                f"Volume name '{volume_name}' already exists (ref: {volume_ref}).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)


def _coerce_simple(value: str):
    v = value.strip()
    if not v:
        return ""
    low = v.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    if low in {"null", "none"}:
        return None
    try:
        if "." in v:
            return float(v)
        return int(v)
    except Exception:
        return v


def parse_extras(s: str) -> dict:
    """Parse comma-separated key=value pairs into a dict with simple coercion."""
    out: dict[str, Any] = {}
    if not s:
        return out
    parts = [p.strip() for p in s.split(",") if p.strip()]
    for part in parts:
        if "=" in part:
            key, val = part.split("=", 1)
            out[key.strip()] = _coerce_simple(val)
        else:
            out[part] = True
    return out


@system_app.command("version")
def system_version(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
) -> None:
    """Display the aggregated controller software version."""

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            summary = client.system.release_summary()
        except RequestError as exc:
            _handle_request_error(exc)
            return

    _echo_json(summary)


@hosts_app.command("membership")
def hosts_membership(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
    output_json: bool = _SHARED_OPTIONS["output_json"],
) -> None:
    """List hosts and indicate whether they belong to a host group."""

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            hosts = client.hosts.list()
            groups = client.hosts.list_groups()
        except RequestError as exc:
            _handle_request_error(exc)
            return

    group_by_cluster: dict[str, str] = {}
    group_by_host_ref: dict[str, str] = {}
    for group in groups:
        label = (group.get("label") or group.get("name") or "").strip()
        cluster_ref = group.get("clusterRef")
        if cluster_ref and label:
            group_by_cluster[cluster_ref] = label
        host_refs = group.get("hostRefs")
        if isinstance(host_refs, list):
            for host_ref in host_refs:
                if isinstance(host_ref, str) and label:
                    group_by_host_ref[host_ref] = label

    memberships: list[dict[str, Any]] = []
    for host in hosts:
        host_ref = host.get("hostRef")
        cluster_ref = host.get("clusterRef")
        group_label = None
        if host_ref and host_ref in group_by_host_ref:
            group_label = group_by_host_ref[host_ref]
        elif cluster_ref and cluster_ref in group_by_cluster:
            group_label = group_by_cluster[cluster_ref]
        memberships.append(
            {
                "hostLabel": host.get("label"),
                "hostRef": host_ref,
                "clusterRef": cluster_ref,
                "hostGroup": group_label,
                "belongsToGroup": bool(group_label),
            }
        )

    _present_output(memberships, view_id="hosts.membership", json_output=output_json)


@volumes_app.command("check-names")
def volumes_check_names(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
) -> None:
    """Report duplicate volume names on the array."""

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            volumes = client.volumes.list()
        except RequestError as exc:
            _handle_request_error(exc)
            return

    duplicates = _collect_duplicate_volume_names(volumes)
    if duplicates:
        typer.secho(
            "Duplicate volume names detected. Review the JSON output before proceeding.",
            err=True,
            fg=typer.colors.RED,
        )
        _echo_json(duplicates)
        raise typer.Exit(code=1)

    typer.secho("All volume names are unique.", fg=typer.colors.GREEN)


@pools_app.command("list")
def pools_list(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
    output_json: bool = _SHARED_OPTIONS["output_json"],
) -> None:
    """List storage pools."""

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            pools = client.pools.list()
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _present_output(pools, view_id="pools.list", json_output=output_json)


@volumes_app.command("list")
def volumes_list(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
    output_json: bool = _SHARED_OPTIONS["output_json"],
) -> None:
    """List volumes present on the array."""

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            volumes = client.volumes.list()
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _present_output(volumes, view_id="volumes.list", json_output=output_json)


def _build_volume_payload(
    pool_id: str,
    name: str,
    size: str,
    size_unit: str,
    raid_level: str | None,
    block_size: int | None,
    data_assurance: bool,
    tags: list[str],
    payload_file: Path | None,
) -> dict[str, Any]:
    if payload_file:
        try:
            return json.loads(payload_file.read_text(encoding="utf-8"))
        except OSError as exc:  # pragma: no cover - filesystem errors
            raise typer.BadParameter(f"Unable to read payload file: {exc}") from exc
        except json.JSONDecodeError as exc:  # pragma: no cover - validated in tests
            raise typer.BadParameter(f"Payload file is not valid JSON: {exc}") from exc

    payload: dict[str, Any] = {
        "poolId": pool_id,
        "name": name,
        "size": size,
        "sizeUnit": size_unit.lower(),
        "dataAssuranceEnabled": data_assurance,
    }
    if raid_level:
        payload["raidLevel"] = raid_level
    if block_size:
        payload["blockSize"] = block_size
    if tags:
        payload["metaTags"] = []
        for entry in tags:
            if "=" not in entry:
                raise typer.BadParameter("Meta tags must be provided as key=value pairs.")
            key, value = entry.split("=", 1)
            payload.setdefault("metaTags", []).append({"key": key, "value": value})
    return payload


def _build_mapping_target_kwargs(
    *,
    host: str | None,
    host_ref: str | None,
    host_group: str | None,
    cluster_ref: str | None,
) -> dict[str, str]:
    options = {
        "host": host,
        "host_ref": host_ref,
        "host_group": host_group,
        "cluster_ref": cluster_ref,
    }
    provided = [key for key, value in options.items() if value]
    if len(provided) != 1:
        raise typer.BadParameter(
            "Provide exactly one of --host, --host-ref, --host-group, or --cluster-ref."
        )
    key = provided[0]
    value = options[key]
    if value is None:  # pragma: no cover - defensive guard
        raise typer.BadParameter("Empty value provided for mapping target option.")
    return {key: value}


@volumes_app.command("create")
def volumes_create(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
    pool_id: str = _VOLUME_CREATE_OPTIONS["pool_id"],
    name: str = _VOLUME_CREATE_OPTIONS["name"],
    size: str = _VOLUME_CREATE_OPTIONS["size"],
    size_unit: str = _VOLUME_CREATE_OPTIONS["size_unit"],
    raid_level: str | None = _VOLUME_CREATE_OPTIONS["raid_level"],
    block_size: int | None = _VOLUME_CREATE_OPTIONS["block_size"],
    data_assurance: bool = _VOLUME_CREATE_OPTIONS["data_assurance"],
    tag: list[str] = _VOLUME_CREATE_OPTIONS["tag"],
    payload_file: Path | None = _VOLUME_CREATE_OPTIONS["payload_file"],
    extras: str | None = _VOLUME_CREATE_OPTIONS["extras"],
    require_unique_name: bool = typer.Option(
        True,
        "--require-unique-name/--allow-duplicate-name",
        help="Validate that no existing volume already uses this name.",
        show_default=True,
    ),
) -> None:
    """Create a new volume within a pool."""

    payload = _build_volume_payload(
        pool_id=pool_id,
        name=name,
        size=size,
        size_unit=size_unit,
        raid_level=raid_level,
        block_size=block_size,
        data_assurance=data_assurance,
        tags=tag,
        payload_file=payload_file,
    )

    # Merge extras (power-user provided key/value pairs) into payload.
    # Extras take precedence over named params by design.
    if extras:
        try:
            extras_dict = parse_extras(extras)
            if isinstance(extras_dict, dict):
                payload.update(extras_dict)
        except Exception:
            raise typer.BadParameter(
                "Invalid format for --extras; expected k=v pairs separated by commas."
            ) from None

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            if require_unique_name:
                _ensure_volume_name_is_unique(client, name)
            result = client.pools.create_volume(pool_id, payload)
        except (RequestError, AuthenticationError) as exc:
            if isinstance(exc, RequestError):
                _handle_request_error(exc)
            else:
                typer.secho(str(exc), err=True, fg=typer.colors.RED)
                raise typer.Exit(code=1) from exc
            return
    _echo_json(result)


@mappings_app.command("list")
def mappings_list(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
    output_json: bool = _SHARED_OPTIONS["output_json"],
    resolve: bool = typer.Option(
        False, "--resolve", help="Resolve IDs to human-readable names (may perform extra requests)."
    ),
) -> None:
    """List volume-to-host or host-group mappings."""

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            if resolve:
                mappings = client.mappings_report()
            else:
                mappings = client.mappings.list()
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _present_output(mappings, view_id="mappings.list", json_output=output_json)


@mappings_app.command("create")
def mappings_create(
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
    volume_ref: str = typer.Option(..., "--volume-ref", help="Volume reference to map."),
    host: str | None = typer.Option(None, "--host", help="Host label to map to."),
    host_ref: str | None = typer.Option(None, "--host-ref", help="Explicit hostRef target."),
    host_group: str | None = typer.Option(None, "--host-group", help="Host group label to use."),
    cluster_ref: str | None = typer.Option(
        None,
        "--cluster-ref",
        help="Explicit clusterRef target.",
    ),
    lun: int | None = typer.Option(None, "--lun", help="Optional explicit LUN value."),
    perms: int | None = typer.Option(None, "--perms", help="Optional permissions mask."),
) -> None:
    """Create a new LUN mapping for a volume."""

    target_kwargs = _build_mapping_target_kwargs(
        host=host,
        host_ref=host_ref,
        host_group=host_group,
        cluster_ref=cluster_ref,
    )

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            result = client.mappings.map_volume(
                volume_ref,
                **target_kwargs,
                lun=lun,
                perms=perms,
            )
        except RequestError as exc:
            _handle_request_error(exc)
            return
        except ResolutionError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc
    _echo_json(result)


@mappings_app.command("remap")
def mappings_remap(
    map_ref: str = typer.Argument(..., help="The ID/Ref of the mapping to move."),
    base_url: str = _SHARED_OPTIONS["base_url"],
    username: str | None = _SHARED_OPTIONS["username"],
    password: str | None = _SHARED_OPTIONS["password"],
    token: str | None = _SHARED_OPTIONS["token"],
    auth: str = _SHARED_OPTIONS["auth"],
    verify_ssl: bool = _SHARED_OPTIONS["verify_ssl"],
    cert_path: Path | None = _SHARED_OPTIONS["cert_path"],
    timeout: float = _SHARED_OPTIONS["timeout"],
    release_version: str | None = _SHARED_OPTIONS["release_version"],
    system_id: str | None = _SHARED_OPTIONS["system_id"],
    target_id: str = typer.Option(
        ..., "--target-id", help="The new target ID (Host or Host Group)."
    ),
    lun: int | None = typer.Option(None, "--lun", help="New LUN number (optional)."),
) -> None:
    """Move an existing mapping to a different target."""

    with _build_client(
        base_url=base_url,
        auth=auth,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    ) as client:
        try:
            result = client.mappings.move(map_ref, target_id, lun=lun)
        except RequestError as exc:
            _handle_request_error(exc)
            return

    _echo_json(result)
