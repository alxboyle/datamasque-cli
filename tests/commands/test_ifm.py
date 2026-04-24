from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from datamasque.client.exceptions import DataMasqueApiError
from typer.testing import CliRunner

from datamasque_cli.main import app
from tests.conftest import make_api_response

MODULE = "datamasque_cli.commands.ifm"


def _endpoint(name: str = "ep-a1b2c3", *, enabled: bool = True) -> dict[str, object]:
    return {
        "name": name,
        "created_time": "2026-01-01T00:00:00+00:00",
        "modified_time": "2026-01-02T00:00:00+00:00",
        "serial": 1,
        "ruleset_yaml": "version: '1.0'\nrules: []\n",
        "options": {
            "enabled": enabled,
            "default_encoding": "json",
            "default_charset": "utf-8",
            "default_log_level": "WARNING",
        },
    }


def _error(status_code: int, *, text: str = "") -> DataMasqueApiError:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return DataMasqueApiError("boom", response=response)


@patch(f"{MODULE}.get_client")
def test_list_renders_flattened_options(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.return_value = make_api_response(
        {"items": [_endpoint("ep-a1b2c3")], "total": 1, "limit": 1, "offset": 0}
    )

    result = runner.invoke(app, ["ifm", "list"])

    assert result.exit_code == 0, result.output
    assert "ep-a1b2c3" in result.stdout
    assert "json" in result.stdout
    assert "WARNING" in result.stdout


@patch(f"{MODULE}.get_client")
def test_list_json_output(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.return_value = make_api_response(
        {"items": [_endpoint("ep-a1b2c3"), _endpoint("ep-z9y8x7")], "total": 2, "limit": 2, "offset": 0}
    )

    result = runner.invoke(app, ["ifm", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [row["name"] for row in payload] == ["ep-a1b2c3", "ep-z9y8x7"]


@patch(f"{MODULE}.get_client")
def test_get_yaml_flag_prints_raw_yaml(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.return_value = make_api_response(_endpoint("ep-a1b2c3"))

    result = runner.invoke(app, ["ifm", "get", "ep-a1b2c3", "--yaml"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "version: '1.0'\nrules: []"


@patch(f"{MODULE}.get_client")
def test_get_not_found_aborts(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.side_effect = _error(404)

    result = runner.invoke(app, ["ifm", "get", "missing-abc123"])

    assert result.exit_code != 0
    assert "not found" in result.stderr.lower()


@patch(f"{MODULE}.get_client")
def test_create_builds_correct_payload_with_defaults(
    mock_get_client: MagicMock, runner: CliRunner, tmp_path: Path
) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.return_value = make_api_response(_endpoint("my-ep-a1b2c3"))

    ruleset_file = tmp_path / "rules.yaml"
    ruleset_file.write_text("version: '1.0'\nrules: []\n")

    result = runner.invoke(app, ["ifm", "create", "--name", "my-ep", "--file", str(ruleset_file)])

    assert result.exit_code == 0, result.output
    client.make_request.assert_called_once()
    call_args = client.make_request.call_args
    assert call_args.args[0] == "POST"
    assert call_args.args[1] == "/api/in-flight/endpoints/"
    body = call_args.kwargs["data"]
    assert body["name"] == "my-ep"
    assert body["ruleset_yaml"] == "version: '1.0'\nrules: []\n"
    assert body["options"] == {
        "enabled": True,
        "default_encoding": "json",
        "default_charset": "utf-8",
        "default_log_level": "WARNING",
    }
    assert "my-ep-a1b2c3" in result.stderr


@patch(f"{MODULE}.get_client")
def test_create_with_overrides(mock_get_client: MagicMock, runner: CliRunner, tmp_path: Path) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.return_value = make_api_response(_endpoint("x-a1b2c3", enabled=False))

    ruleset_file = tmp_path / "rules.yaml"
    ruleset_file.write_text("rules: []\n")

    result = runner.invoke(
        app,
        [
            "ifm",
            "create",
            "--name",
            "x",
            "--file",
            str(ruleset_file),
            "--disabled",
            "--encoding",
            "base64",
            "--charset",
            "ascii",
            "--log-level",
            "DEBUG",
        ],
    )

    assert result.exit_code == 0, result.output
    body = client.make_request.call_args.kwargs["data"]
    assert body["options"] == {
        "enabled": False,
        "default_encoding": "base64",
        "default_charset": "ascii",
        "default_log_level": "DEBUG",
    }


@patch(f"{MODULE}.get_client")
def test_update_merges_existing_options(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.side_effect = [
        make_api_response(_endpoint("ep-a1b2c3", enabled=True)),
        make_api_response(_endpoint("ep-a1b2c3", enabled=False)),
    ]

    result = runner.invoke(app, ["ifm", "update", "ep-a1b2c3", "--disabled"])

    assert result.exit_code == 0, result.output
    assert client.make_request.call_count == 2

    put_call = client.make_request.call_args_list[1]
    assert put_call.args[0] == "PUT"
    assert put_call.args[1] == "/api/in-flight/endpoints/ep-a1b2c3/"
    body = put_call.kwargs["data"]
    assert body["options"]["enabled"] is False
    assert body["options"]["default_encoding"] == "json"
    assert body["options"]["default_charset"] == "utf-8"
    assert body["options"]["default_log_level"] == "WARNING"
    assert body["ruleset_yaml"] == "version: '1.0'\nrules: []\n"


@patch(f"{MODULE}.get_client")
def test_update_requires_a_flag(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client

    result = runner.invoke(app, ["ifm", "update", "ep-a1b2c3"])

    assert result.exit_code != 0
    client.make_request.assert_not_called()


@patch(f"{MODULE}.get_client")
def test_delete_confirmed_calls_api(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.return_value = make_api_response(_endpoint("ep-a1b2c3"))

    result = runner.invoke(app, ["ifm", "delete", "ep-a1b2c3", "--yes"])

    assert result.exit_code == 0, result.output
    methods = [call.args[0] for call in client.make_request.call_args_list]
    assert "DELETE" in methods


@patch(f"{MODULE}.get_client")
def test_delete_aborts_when_missing(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.side_effect = _error(404)

    result = runner.invoke(app, ["ifm", "delete", "missing-abc123", "--yes"])

    assert result.exit_code != 0
    assert "not found" in result.stderr.lower()


@patch(f"{MODULE}.get_client")
def test_license_error_is_friendly(mock_get_client: MagicMock, runner: CliRunner) -> None:
    client = MagicMock()
    mock_get_client.return_value = client
    client.make_request.side_effect = _error(
        403, text='{"detail": "The current license type does not allow access..."}'
    )

    result = runner.invoke(app, ["ifm", "list"])

    assert result.exit_code != 0
    assert "licence" in result.stderr.lower()
