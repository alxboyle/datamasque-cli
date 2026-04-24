"""In-flight masking (IFM) endpoint management commands."""

from __future__ import annotations

from enum import StrEnum
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import typer
from datamasque.client import DataMasqueClient
from datamasque.client.exceptions import DataMasqueApiError
from requests import Response

from datamasque_cli.client import get_client
from datamasque_cli.output import abort, print_success, render_output

app = typer.Typer(help="Manage in-flight masking endpoints.", no_args_is_help=True)

_BASE_PATH = "/api/in-flight/endpoints/"

_LIST_COLUMNS = ["name", "enabled", "encoding", "charset", "log_level", "modified_time"]


class Encoding(StrEnum):
    json = "json"
    base64 = "base64"
    string = "string"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def _detail_path(name: str) -> str:
    return f"{_BASE_PATH}{quote(name, safe='')}/"


def _flatten(endpoint: dict[str, Any]) -> dict[str, Any]:
    options = endpoint.get("options") or {}
    flat: dict[str, Any] = {
        "name": endpoint.get("name"),
        "enabled": options.get("enabled"),
        "encoding": options.get("default_encoding"),
        "charset": options.get("default_charset"),
        "log_level": options.get("default_log_level"),
        "modified_time": endpoint.get("modified_time"),
        "created_time": endpoint.get("created_time"),
        "serial": endpoint.get("serial"),
    }
    return flat


def _ifm_request(
    client: DataMasqueClient,
    method: str,
    path: str,
    *,
    name: str | None = None,
    data: dict[str, Any] | None = None,
) -> Response:
    """Translate IFM-specific error codes into friendly aborts."""
    try:
        return cast(Response, client.make_request(method, path, data=data))
    except DataMasqueApiError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else None

        if status_code == HTTPStatus.NOT_FOUND and name is not None:
            abort(f"Endpoint '{name}' not found.")
        if status_code in (HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.GATEWAY_TIMEOUT):
            abort("In-flight masking server unreachable. Try again shortly.")
        if status_code == HTTPStatus.FORBIDDEN and response is not None:
            body_text = response.text.lower() if response.text else ""
            if "license" in body_text or "licence" in body_text:
                abort("In-flight masking is not enabled on this licence.")
        raise


@app.command("list")
def list_endpoints(
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
    is_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all in-flight masking endpoints."""
    client = get_client(profile)
    response = _ifm_request(client, "GET", _BASE_PATH)
    items = response.json().get("items", [])

    data = [_flatten(item) for item in items]

    if is_json:
        render_output(data, is_json=True)
        return

    render_output(
        [{c: row[c] for c in _LIST_COLUMNS} for row in data],
        is_json=False,
        columns=_LIST_COLUMNS,
        title="In-Flight Endpoints",
    )


@app.command("get")
def get_endpoint(
    name: str = typer.Argument(help="Endpoint name (including server-assigned suffix)"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
    is_yaml: bool = typer.Option(False, "--yaml", help="Output raw ruleset YAML only"),
    is_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show an endpoint's details or ruleset YAML."""
    client = get_client(profile)
    response = _ifm_request(client, "GET", _detail_path(name), name=name)
    body = response.json()

    if is_yaml:
        typer.echo(body.get("ruleset_yaml", ""))
        return

    if is_json:
        render_output(body, is_json=True)
        return

    render_output(_flatten(body), is_json=False, title=f"Endpoint: {name}")


@app.command("create")
def create_endpoint(
    name: str = typer.Option(..., help="Endpoint base name (server appends -XXXXXX)"),
    file: Path = typer.Option(..., "--file", "-f", exists=True, readable=True, help="Path to ruleset YAML file"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Enable or disable the endpoint"),
    encoding: Encoding = typer.Option(Encoding.json, "--encoding", help="Default payload encoding"),
    charset: str = typer.Option("utf-8", "--charset", help="Default charset"),
    log_level: LogLevel = typer.Option(LogLevel.WARNING, "--log-level", help="Default log level"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a new in-flight masking endpoint from a ruleset YAML file."""
    body = {
        "name": name,
        "ruleset_yaml": file.read_text(),
        "options": {
            "enabled": enabled,
            "default_encoding": encoding.value,
            "default_charset": charset,
            "default_log_level": log_level.value,
        },
    }

    client = get_client(profile)
    response = _ifm_request(client, "POST", _BASE_PATH, data=body)
    created_name = response.json().get("name", name)
    print_success(f"Endpoint '{created_name}' created.")


@app.command("update")
def update_endpoint(
    name: str = typer.Argument(help="Endpoint name (including server-assigned suffix)"),
    file: Path | None = typer.Option(
        None, "--file", "-f", exists=True, readable=True, help="Replace ruleset YAML from file"
    ),
    enabled: bool | None = typer.Option(None, "--enabled/--disabled", help="Enable or disable the endpoint"),
    encoding: Encoding | None = typer.Option(None, "--encoding", help="Default payload encoding"),
    charset: str | None = typer.Option(None, "--charset", help="Default charset"),
    log_level: LogLevel | None = typer.Option(None, "--log-level", help="Default log level"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Update an existing in-flight masking endpoint (full-replace under the hood)."""
    if file is None and all(v is None for v in (enabled, encoding, charset, log_level)):
        abort("Nothing to update; pass --file or an options flag.")

    client = get_client(profile)
    existing = _ifm_request(client, "GET", _detail_path(name), name=name).json()
    existing_options = existing.get("options") or {}

    overrides: dict[str, Any] = {
        "enabled": enabled,
        "default_encoding": encoding.value if encoding is not None else None,
        "default_charset": charset,
        "default_log_level": log_level.value if log_level is not None else None,
    }
    body = {
        "name": name,
        "ruleset_yaml": file.read_text() if file is not None else existing.get("ruleset_yaml", ""),
        "options": {**existing_options, **{k: v for k, v in overrides.items() if v is not None}},
    }

    _ifm_request(client, "PUT", _detail_path(name), name=name, data=body)
    print_success(f"Endpoint '{name}' updated.")


@app.command("delete")
def delete_endpoint(
    name: str = typer.Argument(help="Endpoint name (including server-assigned suffix)"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
    is_confirmed: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an in-flight masking endpoint by name."""
    if not is_confirmed:
        typer.confirm(f"Delete endpoint '{name}'?", abort=True)

    client = get_client(profile)
    _ifm_request(client, "DELETE", _detail_path(name), name=name)
    print_success(f"Endpoint '{name}' deleted.")
