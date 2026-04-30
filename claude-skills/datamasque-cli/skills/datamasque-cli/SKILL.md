---
name: datamasque-cli
description: Use when the user wants to interact with a DataMasque instance — start masking runs, check run status, list connections or rulesets, manage seeds, manage ruleset libraries, check system health, or any task involving the DataMasque API. Triggers on "mask the data", "start a run", "check the run", "list connections", "list rulesets", "upload a seed", "check DataMasque health", "dm status", "ruleset library", or any request to operate DataMasque programmatically.
argument-hint: e.g. "start a run with docx_masking on var_input_docx"
user-invocable: true
---

# DataMasque CLI

Operate a DataMasque instance via the `dm` command-line tool.

`dm` is a normal human-facing CLI that adapts when an agent calls it: output
flips to JSON automatically and errors come back as a structured envelope on
stderr with stable exit codes. You don't have to opt in — just call commands.

## Prerequisites

```bash
dm version          # check it's installed
uv tool install datamasque-cli   # install if not
```

## First step: discover the surface

Before composing a sequence of `dm` calls, run `dm catalog --compact` once.
It dumps every subcommand and its help text as JSON, so you can pick the
right command without paging through `--help` screens:

```bash
dm catalog --compact     # ~1.4kB JSON, just {path, help}
dm catalog               # ~10kB, also includes flags and arguments
```

Treat the catalog as the source of truth for what commands exist. The
examples below cover *idiom* — the gotchas that aren't visible from `--help`.

## How output works

`dm` emits JSON automatically when an agent is driving it. You don't need to
pass `--json` — JSON is the default whenever:

- `stdout` is not a TTY (piped, captured, redirected),
- `DM_OUTPUT=json` is set,
- the vendor-neutral `AI_AGENT` env var is set (Claude Code sets this).

Force human-readable tables with `DM_OUTPUT=table` if a human is watching.

## How errors work

In agent mode, every error comes back as JSON on **stderr**, with stdout left
empty so a downstream `jq` or pipe doesn't trip:

```json
{"error": {"code": "not_found", "message": "Connection 'foo' not found.", "hint": "Run dm connections list."}}
```

The `error.code` is one of a stable set — branch on it to decide whether to
retry, fix arguments, or surface the failure to the user. Each maps to a
documented exit code:

| Exit | `error.code`      | Meaning                                        |
| ---: | ----------------- | ---------------------------------------------- |
|    0 | —                 | success                                        |
|    1 | `error`           | unclassified failure                           |
|    2 | —                 | typer/click usage error (unknown flag etc.)    |
|    3 | `not_found`       | resource lookup failed                         |
|    4 | `invalid_input`   | argument values rejected                       |
|    5 | `ambiguous`       | name matched multiple resources                |
|    6 | `auth_required`   | no credentials configured                      |
|    7 | `auth_failed`     | credentials rejected by server                 |
|    8 | `conflict`        | operation rejected by server state             |
|    9 | `transport_error` | network or TLS failure                         |

These are stable across minor versions, so it's safe to write code that
branches on them.

## Authentication

Two options, in priority order:

**Environment variables.** If `DATAMASQUE_URL`, `DATAMASQUE_USERNAME`, and
`DATAMASQUE_PASSWORD` are set, `dm` uses them directly with no profile
needed. This is the right choice for CI and ad-hoc agent runs.

**Saved profile.** For interactive sessions:

```bash
dm auth login --profile <name>   # prompts for URL / username / password
dm auth status                    # show what's currently authenticated
dm auth use <profile>             # switch active profile
```

Add `--insecure` to `auth login` to skip TLS verification (dev / self-signed
certs only). `DATAMASQUE_VERIFY_SSL=false` does the same per-call without
mutating the saved profile.

## Common workflows

### Start a masking run

`dm run start` blocks until the run finishes by default. The CLI inspects
the source connection's type and auto-picks the matching ruleset namespace
(database vs file), so `--ruleset <name>` works even when the same name
exists in both namespaces.

```bash
dm connections list                # find a source connection
dm rulesets list                   # find a ruleset

dm run start \
  --connection <source> \
  --ruleset <ruleset> \
  --destination <dest>             # required for file masking; optional otherwise

# Background mode — return immediately, poll separately.
dm run start -c <source> -r <ruleset> --background

# Pass server-side knobs as repeatable --options key=value pairs.
dm run start -c <source> -r <ruleset> \
  --options batch_size=1000 --options dry_run=true
```

### Monitor and manage runs

```bash
dm run status <run-id>             # one-shot status snapshot
dm run list --status running       # filter by state
dm run wait <run-id>               # block until terminal state
dm run logs <run-id>               # one-shot log dump
dm run logs <run-id> --follow      # stream until terminal state
dm run cancel <run-id>             # exits with code 8 if not cancellable
dm run retry <run-id>              # re-run with the original config
dm run report <run-id> --output report.csv
```

### Connections

```bash
dm connections list                # includes a source/destination role column
dm connections get <name>
dm connections test <name>         # verify reachability without starting a run
dm connections update <name> --password <new>   # preserves the UUID and any references
dm connections delete <name> --yes
```

To create a connection, prefer `--file <connection.json>` for anything beyond
a simple Postgres / S3 / mounted-share — the JSON form supports every
backend type. Quick database example:

```bash
dm connections create --name mydb --type database --db-type postgres \
    --host db.example.com --port 5432 --database mydb \
    --user admin --password secret
```

### Rulesets

DataMasque has two ruleset namespaces — `database` and `file` — so the same
name can legitimately exist in both. Most commands auto-disambiguate, with
`--type file|database` available to pin a specific one.

- `create` reads the server's existing `mask_type` when updating a ruleset by
  name. `--type` is needed only when creating a brand-new ruleset, or when
  two rows share the name and you're updating one of them.
- `get` / `delete` accept `--type` to disambiguate.

```bash
dm rulesets list [--type file]
dm rulesets get <name> [--type file] [--yaml]
dm rulesets create --name <name> --file ruleset.yaml [--type file]
dm rulesets delete <name> [--type file] --yes
dm rulesets validate --file ruleset.yaml --type database
dm rulesets generate --file request.json
```

### Ruleset libraries

```bash
dm libraries list
dm libraries get <name> [--namespace <ns>] [--yaml]
dm libraries create --name <name> --file library.yml [--namespace <ns>]
dm libraries usage <name>          # which rulesets import it — check before deleting
dm libraries delete <name> [--namespace <ns>] [--force]
```

### Discovery

Discovery runs are kicked off as background masking-run jobs. Poll with
`dm run status <run-id>` until terminal, then fetch results.

```bash
dm discover schema <connection>           # start the run, returns a run-id
dm discover schema-results <run-id>       # list detected columns + matches
dm discover sdd-report   <run-id> --output report.csv
dm discover db-report    <run-id> --output report.csv
dm discover file-report  <run-id> --output report.json
```

### System

```bash
dm system health
dm system licence
dm system logs --output logs.tar.gz
dm system upload-licence licence.lic
dm system admin-install --email admin@example.com --username admin
```

### Bundle export / import

For migrating rulesets + libraries + seeds between instances:

```bash
dm rulesets export-bundle --output bundle.zip
dm rulesets import-bundle --file bundle.zip --yes
```

## Gotchas

- **File masking needs `--destination`.** A file-type source masks *into* a
  destination connection — the run fails fast (exit 4) if you forget. Database
  masking is in-place; no destination is allowed there.
- **Library deletion fails on imports.** `dm libraries delete` rejects
  libraries that are still imported by a ruleset. Pass `--force` to delete
  anyway, but run `dm libraries usage <name>` first to see what'll break.
- **Run cancellation depends on state.** `dm run cancel` exits 8 (`conflict`)
  if the run is already in a terminal state — that's normal, not a bug.
- **Run-id from `dm run start` arrives on stderr** as part of the success
  message in human mode; in agent mode you get JSON on stdout when
  `--background` is set, otherwise it blocks and prints the final status.

## Troubleshooting

- **`auth_required` (exit 6):** no profile or env credentials. Run
  `dm auth login` or set `DATAMASQUE_URL`/`USERNAME`/`PASSWORD`.
- **`auth_failed` (exit 7):** credentials rejected by server. Re-check the
  password (it was redacted from any saved config you might be reading).
- **`transport_error` (exit 9):** network/TLS issue. The error message
  includes the URL it tried; if it's a self-signed cert, try `--insecure`
  on `auth login` or `DATAMASQUE_VERIFY_SSL=false`.
- **`not_found` (exit 3):** double-check the name with `dm <thing> list`.
  Names are case-sensitive.
- **Run failed:** `dm run logs <run-id>` shows the worker's output. The CSV
  report (`dm run report <run-id>`) is only generated after a terminal state.
- **Validation failed:** `dm rulesets validate --file <file> --type <type>`
  surfaces the server's error messages without committing the ruleset.
