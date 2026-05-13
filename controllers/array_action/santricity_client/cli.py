"""Command-line interface for interacting with SANtricity arrays."""

from __future__ import annotations

import json
import os
import re
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

_HELP_SETTINGS = {"context_settings": {"help_option_names": ["-h", "--help"]}}
_REPO_VOLUME_NAME_RE = re.compile(r"^repos_\d+$", re.IGNORECASE)

app = typer.Typer(help="SANtricity storage management CLI.", no_args_is_help=True, **_HELP_SETTINGS)

hosts_app = typer.Typer(help="Host operations.", **_HELP_SETTINGS)
pools_app = typer.Typer(help="Pool operations.", **_HELP_SETTINGS)
snapshots_app = typer.Typer(
    help="Snapshot group, image, volume, and schedule operations.", **_HELP_SETTINGS
)
volumes_app = typer.Typer(help="Volume operations.", **_HELP_SETTINGS)
mappings_app = typer.Typer(help="Volume mapping operations.", **_HELP_SETTINGS)
system_app = typer.Typer(help="System metadata operations.", **_HELP_SETTINGS)
reports_app = typer.Typer(help="Pre-filtered report operations.", **_HELP_SETTINGS)
cgs_app = typer.Typer(help="Consistency Group operations.", **_HELP_SETTINGS)
app.add_typer(hosts_app, name="hosts")
app.add_typer(pools_app, name="pools")
app.add_typer(snapshots_app, name="snapshots")
app.add_typer(volumes_app, name="volumes")
app.add_typer(mappings_app, name="mappings")
app.add_typer(system_app, name="system")
app.add_typer(reports_app, name="reports")
app.add_typer(cgs_app, name="consistency-groups")


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


@reports_app.command("interfaces")
def reports_interfaces(
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
    controller: str = typer.Option(
        "all",
        "--controller",
        help="Controller selector: all, a, b, or controller id/ref.",
        show_default=True,
    ),
    protocol: str = typer.Option(
        "all",
        "--protocol",
        help="Protocol filter: all, fibre, ib, iscsi, ethernet.",
        show_default=True,
    ),
) -> None:
    """List normalized host-side interface report rows."""

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
            rows = client.reports.interfaces(controller=controller, protocol=protocol)
        except RequestError as exc:
            _handle_request_error(exc)
            return

    _present_output(rows, view_id="reports.interfaces", json_output=output_json)


@reports_app.command("controllers")
def reports_controllers(
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
    controller: str = typer.Option(
        "all",
        "--controller",
        help="Controller selector: all, a, b, or controller id/ref.",
        show_default=True,
    ),
    protocol: str = typer.Option(
        "all",
        "--protocol",
        help="Host-side protocol filter for embedded interfaces: all, fibre, ib, iscsi, ethernet.",
        show_default=True,
    ),
    include_hostside_interfaces: bool = typer.Option(
        True,
        "--include-hostside-interfaces/--no-hostside-interfaces",
        help="Include embedded host-side interface rows under each controller.",
        show_default=True,
    ),
) -> None:
    """List normalized controller report rows."""

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
            rows = client.reports.controllers(
                controller=controller,
                protocol=protocol,
                include_hostside_interfaces=include_hostside_interfaces,
            )
        except RequestError as exc:
            _handle_request_error(exc)
            return

    _present_output(rows, view_id="reports.controllers", json_output=output_json)


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


def _snapshot_list_command(
    endpoint_method_name: str,
    view_id: str,
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
    output_json: bool,
) -> None:
    """Shared implementation for all snapshot flat-list commands."""
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
            items = getattr(client.snapshots, endpoint_method_name)()
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _present_output(items, view_id=view_id, json_output=output_json)


def _is_snapshot_repo_volume(volume: Mapping[str, Any]) -> bool:
    volume_use = str(volume.get("volumeUse") or "").strip().lower()
    if volume_use in {"concatvolume", "freerepositoryvolume"}:
        return True

    for key in ("label", "name"):
        candidate = volume.get(key)
        if isinstance(candidate, str) and _REPO_VOLUME_NAME_RE.match(candidate.strip()):
            return True
    return False


def _resolve_volume_ref(client: SANtricityClient, volume: str) -> tuple[str, str]:
    """Resolve a user-provided volume label/name/ref to (ref, label)."""
    try:
        volumes = client.volumes.list()
    except RequestError as exc:
        _handle_request_error(exc)
        raise typer.Exit(code=1)

    by_ref = [v for v in volumes if str(v.get("volumeRef") or v.get("id") or "") == volume]
    if by_ref:
        v = by_ref[0]
        return str(v.get("volumeRef") or v.get("id")), str(
            v.get("label") or v.get("name") or volume
        )

    by_label = [v for v in volumes if str(v.get("label") or v.get("name") or "") == volume]
    if not by_label:
        typer.secho(
            f"No volume matching '{volume}' was found.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    if len(by_label) > 1:
        refs = [str(v.get("volumeRef") or v.get("id") or "") for v in by_label]
        typer.secho(
            f"Volume label '{volume}' is not unique. Use a volume ref instead. Matches: {refs}",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    v = by_label[0]
    return str(v.get("volumeRef") or v.get("id")), str(v.get("label") or v.get("name") or volume)


@snapshots_app.command("list-groups")
def snapshots_list_groups(
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
    """List snapshot groups."""
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
            groups = client.snapshots.list_groups()
            schedules = _list_schedules_best_effort(client)
        except RequestError as exc:
            _handle_request_error(exc)
            return

    schedule_counts = _snapshot_schedule_counts(schedules)
    for group in groups:
        group_ref = str(group.get("pitGroupRef") or group.get("id") or "")
        schedule_count = schedule_counts.get(group_ref, 0)
        group["scheduleCount"] = schedule_count
        group["isScheduleOwned"] = schedule_count > 0

    _present_output(groups, view_id="snapshots.list-groups", json_output=output_json)


@snapshots_app.command("list-images")
def snapshots_list_images(
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
    """Legacy alias of list-snapshots using image terminology."""
    typer.secho(
        "list-images is a legacy alias; prefer list-snapshots.",
        err=True,
        fg=typer.colors.YELLOW,
    )
    snapshots_list_snapshots(
        base_url=base_url,
        username=username,
        password=password,
        token=token,
        auth=auth,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
        output_json=output_json,
    )


@snapshots_app.command("list-snapshots")
def snapshots_list_snapshots(
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
    """List all snapshots across all snapshot groups."""
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
            images = client.snapshots.list_all_images()
            groups = client.snapshots.list_groups()
        except RequestError as exc:
            _handle_request_error(exc)
            return
    group_name_by_ref: dict[str, str] = {
        g["pitGroupRef"]: (g.get("name") or g.get("label") or g["pitGroupRef"])
        for g in groups
        if "pitGroupRef" in g
    }
    for image in images:
        pgr = image.get("pitGroupRef")
        image["snapshotGroupName"] = group_name_by_ref.get(pgr, pgr or "")
    _present_output(images, view_id="snapshots.list-images", json_output=output_json)


@snapshots_app.command("list-volumes")
def snapshots_list_volumes(
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
    """List snapshot volumes (linked clones and read-only views)."""
    _snapshot_list_command(
        "list_volumes",
        "snapshots.list-volumes",
        base_url,
        auth,
        username,
        password,
        token,
        verify_ssl,
        cert_path,
        timeout,
        release_version,
        system_id,
        output_json,
    )


@snapshots_app.command("list-repo-groups")
def snapshots_list_repos(
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
    """List concatenated repository volumes backing snapshot groups and linked clones."""
    _snapshot_list_command(
        "list_repositories",
        "snapshots.list-repo-groups",
        base_url,
        auth,
        username,
        password,
        token,
        verify_ssl,
        cert_path,
        timeout,
        release_version,
        system_id,
        output_json,
    )


@snapshots_app.command("list-repo-volumes")
def snapshots_list_repo_volumes(
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
    """List repository-related volumes, including active concat volumes and reusable free repository members."""
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

    repo_volumes = [
        volume
        for volume in volumes
        if isinstance(volume, Mapping) and _is_snapshot_repo_volume(volume)
    ]
    _present_output(repo_volumes, view_id="snapshots.list-repo-volumes", json_output=output_json)


@snapshots_app.command("list-group-util")
def snapshots_list_group_util(
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
    """List repository utilization for each snapshot group."""
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
            utilization = client.snapshots.list_group_repo_utilization()
            groups = client.snapshots.list_groups()
            schedules = _list_schedules_best_effort(client)
        except RequestError as exc:
            _handle_request_error(exc)
            return

    group_name_by_ref: dict[str, str] = {
        str(g.get("pitGroupRef") or g.get("id") or ""): (
            g.get("name") or g.get("label") or str(g.get("pitGroupRef") or g.get("id") or "")
        )
        for g in groups
        if g.get("pitGroupRef") or g.get("id")
    }
    schedule_counts = _snapshot_schedule_counts(schedules)
    for item in utilization:
        group_ref = str(item.get("groupRef") or "")
        item["snapshotGroupName"] = group_name_by_ref.get(group_ref, group_ref)
        schedule_count = schedule_counts.get(group_ref, 0)
        item["scheduleCount"] = schedule_count
        item["isScheduleOwned"] = schedule_count > 0

    _present_output(utilization, view_id="snapshots.list-group-util", json_output=output_json)


@snapshots_app.command("list-volume-util")
def snapshots_list_volume_util(
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
    """List repository utilization for snapshot volumes (linked clones)."""
    _snapshot_list_command(
        "list_volume_repo_utilization",
        "snapshots.list-volume-util",
        base_url,
        auth,
        username,
        password,
        token,
        verify_ssl,
        cert_path,
        timeout,
        release_version,
        system_id,
        output_json,
    )


@snapshots_app.command("list-cg-members")
def snapshots_list_cg_members(
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
    """List volumes that are members of consistency groups."""
    _snapshot_list_command(
        "list_consistency_group_members",
        "snapshots.list-cg-members",
        base_url,
        auth,
        username,
        password,
        token,
        verify_ssl,
        cert_path,
        timeout,
        release_version,
        system_id,
        output_json,
    )


@snapshots_app.command("list-schedules")
def snapshots_list_schedules(
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
    """List snapshot schedules."""
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
            schedules = client.snapshots.list_schedules()
            groups = client.snapshots.list_groups()
        except RequestError as exc:
            _handle_request_error(exc)
            return
    group_name_by_ref: dict[str, str] = {
        g["pitGroupRef"]: (g.get("name") or g.get("label") or g["pitGroupRef"])
        for g in groups
        if "pitGroupRef" in g
    }
    for sched in schedules:
        target = sched.get("targetObject")
        sched["snapshotGroupName"] = group_name_by_ref.get(target, target or "")
    _present_output(schedules, view_id="snapshots.list-schedules", json_output=output_json)


@snapshots_app.command("create-image")
def snapshots_create_image(
    group_ref: str = typer.Argument(..., help="Snapshot group ref (pitGroupRef) to snapshot."),
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
    """Create a new snapshot image in a snapshot group."""
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
            image = client.snapshots.create_image(group_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(image)


@snapshots_app.command("create-repo-group")
def snapshots_create_repo_group(
    volume: str = typer.Option(..., "--volume", help="Base volume label/name or volumeRef."),
    percent_capacity: int = typer.Option(
        ..., "--percent-capacity", min=1, max=100, help="Repository capacity as % of base volume."
    ),
    use_free_repository_volumes: bool = typer.Option(
        False,
        "--use-free-repository-volumes/--no-use-free-repository-volumes",
        help="Try to reuse free repository volumes when available.",
        show_default=True,
    ),
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
    """Legacy alias for planning a snapshot repository-group candidate."""
    typer.secho(
        "create-repo-group is a planning alias only; SANtricity creates repository groups when you create a snapshot group or snapshot volume.",
        err=True,
        fg=typer.colors.YELLOW,
    )
    snapshots_plan_repo_group(
        volume=volume,
        percent_capacity=percent_capacity,
        use_free_repository_volumes=use_free_repository_volumes,
        base_url=base_url,
        username=username,
        password=password,
        token=token,
        auth=auth,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    )


@snapshots_app.command("plan-repo-group")
def snapshots_plan_repo_group(
    volume: str = typer.Option(..., "--volume", help="Base volume label/name or volumeRef."),
    percent_capacity: int = typer.Option(
        ..., "--percent-capacity", min=1, max=100, help="Repository capacity as % of base volume."
    ),
    use_free_repository_volumes: bool = typer.Option(
        False,
        "--use-free-repository-volumes/--no-use-free-repository-volumes",
        help="Try to reuse free repository volumes when available.",
        show_default=True,
    ),
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
    """Return repository-group candidate data for later snapshot-group creation."""
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
        volume_ref, _ = _resolve_volume_ref(client, volume)
        try:
            candidates = client.snapshots.get_repo_group_candidates_single(
                base_volume_ref=volume_ref,
                percent_capacity=percent_capacity,
                use_free_repository_volumes=use_free_repository_volumes,
            )
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(candidates)


@snapshots_app.command("create-snapshot-group")
def snapshots_create_snapshot_group(
    volume: str = typer.Option(..., "--volume", help="Base volume label/name or volumeRef."),
    percent_capacity: int = typer.Option(
        ..., "--percent-capacity", min=1, max=100, help="Repository capacity as % of base volume."
    ),
    name: str | None = typer.Option(
        None, "--name", help="Snapshot group name. Defaults to <volume_label>_SG_01."
    ),
    warning_threshold: int = typer.Option(
        75, "--warning-threshold", min=1, max=100, help="Repository full warning threshold percent."
    ),
    auto_delete_limit: int = typer.Option(
        32,
        "--auto-delete-limit",
        min=0,
        help="Auto-delete limit when full policy purges snapshots.",
    ),
    full_policy: str = typer.Option(
        "purgepit", "--full-policy", help="Repository full policy (for example: purgepit)."
    ),
    use_free_repository_volumes: bool = typer.Option(
        False,
        "--use-free-repository-volumes/--no-use-free-repository-volumes",
        help="Try to reuse free repository volumes when available.",
        show_default=True,
    ),
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
    """Create a snapshot group for a volume, which also creates its repository backing."""
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
        volume_ref, volume_label = _resolve_volume_ref(client, volume)
        try:
            candidates = client.snapshots.get_repo_group_candidates_single(
                base_volume_ref=volume_ref,
                percent_capacity=percent_capacity,
                use_free_repository_volumes=use_free_repository_volumes,
            )
        except RequestError as exc:
            _handle_request_error(exc)
            return

        if not isinstance(candidates, list) or not candidates or "candidate" not in candidates[0]:
            typer.secho(
                "Unexpected repository candidate response from array.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

        payload = {
            "baseMappableObjectId": volume_ref,
            "name": name or f"{volume_label}_SG_01",
            "repositoryCandidate": candidates[0]["candidate"],
            "warningThreshold": warning_threshold,
            "autoDeleteLimit": auto_delete_limit,
            "fullPolicy": full_policy,
        }

        try:
            group = client.snapshots.create_snapshot_group(payload)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(group)


@snapshots_app.command("create-snapshot")
def snapshots_create_snapshot(
    group_ref: str | None = typer.Option(
        None, "--group-ref", help="Snapshot group ref (pitGroupRef)."
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        help="Auto-select a snapshot group for --volume, excluding schedule-owned groups by default.",
        show_default=True,
    ),
    include_schedule_owned_groups: bool = typer.Option(
        False,
        "--include-schedule-owned-groups/--exclude-schedule-owned-groups",
        help="Allow auto-selection to use schedule-owned snapshot groups.",
        show_default=True,
    ),
    min_free_percent: float = typer.Option(
        0.0,
        "--min-free-percent",
        min=0.0,
        max=100.0,
        help="Minimum free repository capacity required before snapshot creation in auto mode.",
        show_default=True,
    ),
    auto_grow_if_needed: bool = typer.Option(
        True,
        "--auto-grow-if-needed/--no-auto-grow-if-needed",
        help="When no group meets minimum free capacity, attempt to expand one eligible group.",
        show_default=True,
    ),
    growth_step_percent: int = typer.Option(
        10,
        "--growth-step-percent",
        min=1,
        max=100,
        help="Expansion candidate percent of base volume when auto-grow is needed.",
        show_default=True,
    ),
    max_repo_group_capacity_percent: float = typer.Option(
        100.0,
        "--max-repo-group-capacity-percent",
        min=1.0,
        max=100.0,
        help="Do not auto-grow groups already at or above this repository-size percent of base volume.",
        show_default=True,
    ),
    max_repo_volumes_per_group: int = typer.Option(
        16,
        "--max-repo-volumes-per-group",
        min=1,
        max=16,
        help="Do not auto-grow groups with this many repository members already attached.",
        show_default=True,
    ),
    volume: str | None = typer.Option(
        None, "--volume", help="Optional base volume label/name/ref to validate group ownership."
    ),
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
    """Create a snapshot in an existing snapshot group.

    Provide `--group-ref` directly, or use `--auto --volume <name-or-ref>`
    to choose an eligible group automatically.
    """
    if not group_ref and not auto:
        typer.secho(
            "Either --group-ref or --auto is required.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    if auto and not group_ref and not volume:
        typer.secho(
            "--volume is required when using --auto without --group-ref.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

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
        volume_ref: str | None = None
        if volume:
            volume_ref, _ = _resolve_volume_ref(client, volume)

        if not volume_ref:
            typer.secho("The '--volume' argument is required when using '--auto'.", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)

        try:
            from .automation.snapshots import SnapshotsAutomation

            auto_api = SnapshotsAutomation(client)
            snapshot = auto_api.auto_create_snapshot(
                volume_ref=volume_ref,
                min_free_percent=min_free_percent,
                auto_grow_if_needed=auto_grow_if_needed,
                growth_step_percent=growth_step_percent,
                include_schedule_owned_groups=include_schedule_owned_groups,
                max_repo_group_capacity_percent=max_repo_group_capacity_percent,
                max_repo_volumes_per_group=max_repo_volumes_per_group,
            )
        except RuntimeError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
        except RequestError as exc:
            _handle_request_error(exc)
            raise typer.Exit(code=1)
        except ValueError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)

    _echo_json(snapshot)


@snapshots_app.command("create-clone")
def snapshots_create_clone(
    snapshot_id: str = typer.Option(
        ...,
        "--snapshot-id",
        help="Identifier of the source snapshot image (pitRef / snapshotImageId).",
    ),
    name: str = typer.Option(..., "--name", help="Name of the new snapshot volume (Linked Clone)."),
    clone_type: str = typer.Option("ro", "--type", help="Clone type ('ro' is read-only)."),
    extras: str | None = typer.Option(
        None, "--extras", help="Comma-separated optional payload fields (e.g. k=v,flag=true)."
    ),
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
    """Create a new Snapshot Volume (Linked Clone)."""
    if clone_type.lower() != "ro":
        typer.secho(
            "Error: '--type rw' (Read-Write linked clones) requires repository automation that is not yet implemented. Use '--type ro' for now.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    payload: dict[str, Any] = {
        "name": name,
        "snapshotImageId": snapshot_id,
        "viewMode": "readOnly",
    }
    if extras:
        try:
            payload.update(parse_extras(extras))
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
            clone = client.snapshots.create_snapshot_volume(payload)
        except RequestError as exc:
            _handle_request_error(exc)
            return
        _echo_json(clone)


@snapshots_app.command("delete-image")
def snapshots_delete_image(
    image_ref: str = typer.Argument(..., help="Snapshot image ref (pitRef / id) to delete."),
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
    """Legacy alias of delete-snapshot using image terminology."""
    typer.secho(
        "delete-image is a legacy alias; prefer delete-snapshot.",
        err=True,
        fg=typer.colors.YELLOW,
    )
    snapshots_delete_snapshot(
        snapshot_ref=image_ref,
        base_url=base_url,
        username=username,
        password=password,
        token=token,
        auth=auth,
        verify_ssl=verify_ssl,
        cert_path=cert_path,
        timeout=timeout,
        release_version=release_version,
        system_id=system_id,
    )


@snapshots_app.command("delete-snapshot")
def snapshots_delete_snapshot(
    snapshot_ref: str = typer.Argument(..., help="Snapshot ref (pitRef / id) to delete."),
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
    """Delete a snapshot by its ref."""
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
            client.snapshots.delete_snapshot(snapshot_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    typer.secho(f"Snapshot {snapshot_ref!r} deleted.", fg=typer.colors.GREEN)


@snapshots_app.command("delete-group")
def snapshots_delete_group(
    group_ref: str = typer.Argument(..., help="Snapshot group ref (pitGroupRef / id) to delete."),
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
    """Delete a snapshot group by group ref."""
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
            client.snapshots.delete_snapshot_group(group_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    typer.secho(f"Snapshot group {group_ref!r} deleted.", fg=typer.colors.GREEN)


@snapshots_app.command("delete-repo-group")
def snapshots_delete_repo_group(
    repo_group_ref: str = typer.Argument(..., help="Repository group ref (concatVolRef / id)."),
) -> None:
    """Explain current API limitation for standalone repo-group deletion."""
    _ = repo_group_ref  # keep argument explicit for future API support
    typer.secho(
        "SANtricity does not expose a standalone delete endpoint for repository concat groups in this workflow. "
        "Delete the owning snapshot group or snapshot volume instead.",
        err=True,
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=1)


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


@volumes_app.command("delete")
def volumes_delete(
    volume_ref: str = typer.Argument(..., help="The ID/Ref of the volume to delete."),
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
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation prompt.", show_default=True
    ),
) -> None:
    """Delete a volume."""

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
        if not force:
            typer.confirm(f"Are you sure you want to delete volume '{volume_ref}'?", abort=True)

        try:
            result = client.volumes.delete(volume_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return

    typer.secho(f"Volume '{volume_ref}' deleted.", fg=typer.colors.GREEN)
    if result:
        _echo_json(result)


@volumes_app.command("expand")
def volumes_expand(
    volume_ref: str = typer.Argument(..., help="The ID/Ref of the volume to expand."),
    size: float = typer.Argument(..., help="New total capacity of the volume."),
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
    unit: str = typer.Option(
        "gb",
        "--unit",
        help="Unit for size (bytes, kb, mb, gb, tb).",
        show_default=True,
    ),
) -> None:
    """Expand a volume to a new target capacity."""

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
            result = client.volumes.expand(volume_ref, size, unit=unit)
        except RequestError as exc:
            _handle_request_error(exc)
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


@mappings_app.command("delete")
def mappings_delete(
    map_ref: str = typer.Argument(..., help="The ID/Ref of the mapping to remove."),
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
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation prompt.", show_default=True
    ),
) -> None:
    """Remove a mapping."""

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
        if not force:
            typer.confirm(f"Are you sure you want to delete mapping '{map_ref}'?", abort=True)

        try:
            client.mappings.delete(map_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return

    typer.secho(f"Mapping '{map_ref}' deleted.", fg=typer.colors.GREEN)

def _list_schedules_best_effort(client):
    try:
        return client.snapshots.list_schedules()
    except Exception as exc:
        return []

def _snapshot_schedule_counts(schedules):
    counts = {}
    for schedule in schedules:
        target = schedule.get("targetObject")
        if target:
            counts[str(target)] = counts.get(str(target), 0) + 1
    return counts


# ==============================================================================
# Consistency Groups
# ==============================================================================

@cgs_app.command("list")
def cgs_list(
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
    """List all consistency groups."""
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
            cgs = client.consistency_groups.list_groups()
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(cgs)


@cgs_app.command("list-members")
def cgs_list_members(
    group: str = typer.Option(..., "--group", help="Consistency Group ID or name."),
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
    """List member volumes of a consistency group."""
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
            # Simple resolve for name -> cgRef
            cgs = client.consistency_groups.list_groups()
            cg_ref = next((c["id"] for c in cgs if c["id"] == group or c["name"] == group), group)
            members = client.consistency_groups.list_member_volumes(cg_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(members)


@cgs_app.command("list-snapshots")
def cgs_list_snapshots(
    group: str = typer.Option(..., "--group", help="Consistency Group ID or name."),
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
    """List snapshots for a consistency group."""
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
            cgs = client.consistency_groups.list_groups()
            cg_ref = next((c["id"] for c in cgs if c["id"] == group or c["name"] == group), group)
            snapshots = client.consistency_groups.list_snapshots(cg_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(snapshots)


@cgs_app.command("list-clones")
def cgs_list_clones(
    group: str = typer.Option(..., "--group", help="Consistency Group ID or name."),
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
    """List read-only Linked Clones (Views) for a consistency group."""
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
            cgs = client.consistency_groups.list_groups()
            cg_ref = next((c["id"] for c in cgs if c["id"] == group or c["name"] == group), group)
            views = client.consistency_groups.list_views_for_group(cg_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(views)


@cgs_app.command("create")
def cgs_create(
    name: str = typer.Option(..., "--name", help="Name of the new Consistency Group."),
    full_warn_threshold: int = typer.Option(75, "--warning-threshold", help="Full warning threshold percent."),
    auto_delete_limit: int = typer.Option(32, "--auto-delete-limit", help="Auto delete limit for purge policy."),
    full_policy: str = typer.Option("purgepit", "--full-policy", help="Repository full policy (e.g., purgepit)."),
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
    """Create a new consistency group."""
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
            payload = {
                "name": name,
                "fullWarnThresholdPercent": full_warn_threshold,
                "autoDeleteThreshold": auto_delete_limit, # wait, standard API might be 'autoDeleteLimit' or 'autoDeleteThreshold'
                "repositoryFullPolicy": full_policy,
            }
            # Notes used autoDeleteThreshold in POST /consistency-groups
            cg = client.consistency_groups.create_group(payload)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(cg)


@cgs_app.command("create-snapshot")
def cgs_create_snapshot(
    group: str = typer.Option(..., "--group", help="Consistency Group ID or name."),
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
    """Create a new snapshot for a consistency group. Will error if member volumes are empty."""
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
            cgs = client.consistency_groups.list_groups()
            cg_ref = next((c["id"] for c in cgs if c["id"] == group or c["name"] == group), group)
            # Use automation safe-wrapper
            snaps = client.automation.snapshots.create_cg_snapshot(cg_ref)
        except RuntimeError as err:
            typer.secho(str(err), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(snaps)



@cgs_app.command("add-member")
def cgs_add_member(
    group: str = typer.Option(..., "--group", help="Consistency Group ID or name."),
    volume: str = typer.Option(..., "--volume", help="Volume ID to add to the CG."),
    repository_percent: int = typer.Option(20, "--repository-percent", help="Repository size percent for this member."),
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
    """Add a member volume to a consistency group."""
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
            # Simple resolve for name -> cgRef
            cgs = client.consistency_groups.list_groups()
            cg_ref = next((c["id"] for c in cgs if c["id"] == group or c["name"] == group), group)
            
            # Since repository Candidate needs to be populated, SANtricity might do it server-side if pool is defined.
            # But the 'add_member_volume' logic for CSI assumes the repositoryCandidate or poolId.
            # For now, sending what the API generally validates or throwing error on mismatch.
            payload = {
                "volumeId": volume,
                "repositoryPercent": repository_percent,
                "scanMedia": False,
                "validateParity": False,
            }
            # Add member natively
            members = client.consistency_groups.add_member_volume(cg_ref, payload)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    _echo_json(members)


@cgs_app.command("delete")
def cgs_delete(
    group: str = typer.Option(..., "--group", help="Consistency Group ID or name to delete."),
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
    """Delete a consistency group."""
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
            cgs = client.consistency_groups.list_groups()
            cg_ref = next((c["id"] for c in cgs if c["id"] == group or c["name"] == group), group)
            client.consistency_groups.delete_group(cg_ref)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    typer.secho(f"Successfully deleted Consistency Group: {group}", fg=typer.colors.GREEN)



@cgs_app.command("remove-member")
def cgs_remove_member(
    group: str = typer.Option(..., "--group", help="Consistency Group ID or name."),
    member: str = typer.Option(..., "--member", help="Member Volume ID to remove from the CG."),
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
    """Remove a member volume from a consistency group. May fail if dependent clones exist."""
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
            # Simple resolve for name -> cgRef
            cgs = client.consistency_groups.list_groups()
            cg_ref = next((c["id"] for c in cgs if c["id"] == group or c["name"] == group), group)
            
            client.consistency_groups.remove_member_volume(cg_ref, member)
        except RequestError as exc:
            _handle_request_error(exc)
            return
    typer.secho(f"Successfully removed member {member} from CG.", fg=typer.colors.GREEN)

