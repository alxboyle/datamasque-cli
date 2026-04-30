"""DataMasque CLI entry point.

Usage:
    dm auth login
    dm run start --connection mydb --ruleset myrules
    dm run list --status running
    dm rulesets list --json
"""

from __future__ import annotations

from importlib.metadata import version as pkg_version
from typing import Any

import click
import typer
from rich.console import Console

from datamasque_cli.commands import (
    auth,
    connections,
    discovery,
    files,
    ruleset_libraries,
    rulesets,
    runs,
    seeds,
    system,
    users,
)
from datamasque_cli.output import print_json, should_emit_json, stdout_console

app = typer.Typer(
    name="dm",
    help="DataMasque CLI — manage data masking from the command line.",
    no_args_is_help=True,
)

app.add_typer(auth.app, name="auth")
app.add_typer(connections.app, name="connections")
app.add_typer(rulesets.app, name="rulesets")
app.add_typer(runs.app, name="run")
app.add_typer(users.app, name="users")
app.add_typer(discovery.app, name="discover")
app.add_typer(seeds.app, name="seeds")
app.add_typer(files.app, name="files")
app.add_typer(system.app, name="system")
app.add_typer(ruleset_libraries.app, name="libraries")


@app.command()
def version() -> None:
    """Show the CLI version."""
    console = Console(stderr=True)
    console.print("  [#7B36F5]▷◁[/#7B36F5]  ", end="")
    console.print("[bold #7B36F5]DataMasque[/bold #7B36F5] CLI", end="  ")
    typer.echo(f"v{pkg_version('datamasque-cli')}")


def _walk_commands(group: click.Group, path_prefix: str = "") -> list[dict[str, Any]]:
    """Walk a click group recursively and yield one entry per leaf command.

    Each entry has `path` (space-separated), `help` (first sentence of the
    docstring), and `options` (a flat list of flags + arguments).
    """
    items: list[dict[str, Any]] = []
    for name, cmd in sorted(group.commands.items()):
        if cmd.hidden:
            continue
        path = f"{path_prefix} {name}".strip()
        if isinstance(cmd, click.Group):
            items.extend(_walk_commands(cmd, path))
            continue
        options: list[dict[str, Any]] = []
        for param in cmd.params:
            if isinstance(param, click.Option):
                options.append(
                    {
                        "flags": list(param.opts),
                        "help": param.help or "",
                        "required": param.required,
                        "is_flag": param.is_flag,
                    }
                )
            elif isinstance(param, click.Argument):
                options.append(
                    {
                        "name": param.name,
                        "required": param.required,
                        "is_argument": True,
                    }
                )
        # Take only the first paragraph of help text — keeps the catalog dense.
        help_text = (cmd.help or "").strip().split("\n\n", 1)[0].replace("\n", " ")
        items.append({"path": path, "help": help_text, "options": options})
    return items


@app.command()
def catalog(
    is_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    is_compact: bool = typer.Option(
        False, "--compact", help="Drop options/arguments — show only command paths and help."
    ),
) -> None:
    """Dump the full CLI command tree for agent discovery.

    Designed to be called once at session start so an agent can introspect
    every available subcommand without parsing per-command --help screens.
    """
    from typer.main import get_command

    click_app = get_command(app)
    if not isinstance(click_app, click.Group):
        # Defensive — a Typer app with subcommands always materialises as a Group.
        raise RuntimeError("Root command is not a click Group; cannot walk catalog.")
    items = _walk_commands(click_app)
    if is_compact:
        items = [{"path": item["path"], "help": item["help"]} for item in items]

    if should_emit_json(is_json):
        print_json({"commands": items})
        return

    # Human mode: render a flat indented list. Tables would balloon the width
    # and obscure that the structure is `<group> <subcommand>`.
    width = max(len(item["path"]) for item in items) if items else 0
    for item in items:
        stdout_console.print(f"  [bold]{item['path']:<{width}}[/bold]  [dim]{item['help']}[/dim]")


if __name__ == "__main__":
    app()
