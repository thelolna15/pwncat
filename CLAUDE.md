# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session startup

Before any structural exploration of this codebase, verify the `codebase-memory` knowledge-graph index is current for this project (`index_status`, and `detect_changes` if work has happened since the last index). If the index is stale, missing, or reports gaps for files you rely on, re-run `index_repository` (or fall back to `Read`/`Grep` on the reported-uncovered paths) before trusting `search_graph`/`trace_path` results.

## Development workflow

- Do all feature/bugfix work on a branch; never commit directly to `master` (this repo's default branch — the project calls it `master`, not `main`). Merge to `master` only once the change is verified (formatting + lint clean, tests pass, reviewed).
- Existing project convention (CONTRIBUTING.md), not new: pure bug fixes target `master`; anything adding functionality targets the latest `release-vX.Y.Z` branch instead.
- Pick the Superpowers / mattpocock-skills workflow that matches the work, rather than diving straight into code: `superpowers:brainstorming` before any new feature or design decision, `superpowers:test-driven-development` while implementing, `superpowers:systematic-debugging` for bug investigation, `mattpocock-skills:code-review` (or `code-review`) before a merge.
- Before merging anything into `master`, run `/humanizer:humanizer` and `/antislop` over any new prose, comments, or docs to strip AI-slop phrasing.
- Write all code, comments, commit messages, and PR descriptions in English (existing project convention).
- Add a one-line entry to `CHANGELOG.md` under `[Unreleased]` for every user-facing change (existing CONTRIBUTING.md rule); tag bug-fix PRs with `Fixes #XXX` only if the fix is complete.

## Commands

Setup:
```sh
poetry install
poetry shell
```

Formatting/linting (run from repo root before any PR):
```sh
isort ./pwncat
black ./pwncat
flake8
```

Tests (pytest, suite lives in `tests/`):
```sh
# Full suite against disposable podman containers (centos + ubuntu bind shells)
./run-tests.sh

# Single test file / function, once target containers/hosts are reachable
CENTOS_HOST=127.0.0.1 CENTOS_BIND_PORT=4444 UBUNTU_HOST=127.0.0.1 UBUNTU_BIND_PORT=4445 \
    pytest tests/test_platform.py::test_name -v

# Include a Windows target
WINDOWS_HOST=10.10.10.10 WINDOWS_BIND_PORT=4444 ./run-tests.sh
```
Target host/port env vars are consumed by fixtures in `tests/conftest.py`; without them, platform-dependent tests are skipped rather than failed.

Running pwncat itself:
```sh
pwncat-cs [protocol://][user[:password]@][host][:port]   # installed entry point
python -m pwncat ...                                      # equivalent, from a checkout
```
`test.py` is a throwaway script demonstrating manual `Manager`/listener usage for local experimentation — not part of the test suite.

## Architecture

pwncat is layered bottom-up; each layer only talks to the one directly below it.

1. **`pwncat/channel`** — raw byte-stream transport, with no protocol awareness. `Channel` (ABC, `channel/__init__.py`) defines `send`/`recv`/`recvuntil`/`peek`/`makefile`; concrete classes are `Socket`/`Bind`/`Connect`/`SSLBind`/`SSLConnect` (plain/TLS TCP, one file each) and `Ssh` (paramiko-backed). `channel.create(protocol=None, **kwargs)` looks classes up by registered name and, when no protocol is given, infers one from kwargs (`user` set → `ssh`; no host or `0.0.0.0` → `bind`; otherwise → `connect`; `ssl`/certfile/keyfile prefixes `ssl-`). `reconnect://` is **not** a registered channel protocol despite appearing in the README/`--help` examples — reconnecting to a known host goes through an installed `implant.remote` Fact instead, handled ad hoc in `__main__.py` and `commands/connect.py`.

2. **`pwncat/platform`** — turns a connected `Channel` into a working shell/process-execution abstraction. `Platform` (ABC, `platform/__init__.py`) standardizes filesystem ops, user/identity info, `which`, and process execution (`Popen` → `run`, backed by `pwncat/subprocess.py`'s `Popen`/`CompletedProcess`); its `__init__` calls `channel.connect()` and mints a platform-bound `Path` class per instance by mixing the generic `Path` helper with `pathlib.Pure*Path`. `Linux` (`platform/linux.py`) drives a real POSIX shell by echoing random start/end/exit-code delimiters around each command and framing stdout through `channel.makefile()`; only one command may be in flight at a time (`self.command_running`). `Windows` (`platform/windows.py`) instead side-loads a .NET "stage two" C2 via `InstallUtil.exe` and speaks a JSON+gzip+base64 RPC (`run_method`) — a completely different command-transport model hidden behind the same `Popen`/`run` interface. Windows has no custom `Path` subclass (unlike Linux's `LinuxPath`), so some of the base `Path`'s POSIX-flavored default logic (readable/writable via stat mode bits) doesn't meaningfully apply to it.

3. **`pwncat/manager.py`** — `Session` binds one `Channel` + one `Platform` + a persistent `Target` (looked up/created in ZODB by `platform.get_host_hash()`, so the same host reached via different channels or protocols resolves to the same `Target`). `Manager` is the composition root and a context manager: it owns `Config`, the ZODB `db`, the module registry (`load_modules`, via `pkgutil.walk_packages` over `pwncat.modules`), the `CommandParser`, all live `Session`s, and background `Listener` threads for catching reverse shells. `Manager.interactive()` is pwncat's main loop — a local prompt until a target is focused, then it pumps channel bytes through the platform's interactive loop.

4. **`pwncat/modules` + `pwncat/facts` + persistence (`pwncat/db.py`, `pwncat/target.py`)** — all functionality (enumeration, privilege escalation, persistence/implants) is implemented as a `Module`. A module's dotted name (`enumerate.*`, `escalate.*`, `implant.*`, prefixed `linux.`/`windows.`/`agnostic.`) is derived purely from its file path under `pwncat/modules/`, not a declared field — `load_modules` strips the `pwncat.modules.` prefix off the import path. `EnumerateModule` subclasses implement `enumerate(session)` as a generator yielding `Fact` objects; the frozen base `run()` (injected by `BaseModuleMeta`) handles cache/schedule bookkeeping (`Schedule.ONCE`/`PER_USER`/`ALWAYS`), wraps the call in a ZODB transaction, and calls `session.register_fact()`. Escalation and implant installation are not separate module types — they are `EnumerateModule`/`ImplantModule` subclasses that produce behavior-carrying `Fact` subclasses (`EscalationReplace`, `EscalationSpawn`, `Implant`) with methods like `.execute()`/`.trigger()`. `Fact` dedup is attribute-wise `__eq__`. Persistence is ZODB (`persistent.Persistent`/`PersistentList`/`OOBTree`), not SQL: `Target` is the per-host record in `root.targets`, keyed by GUID; the `db` config URI defaults to `memory://` (non-persistent) unless pointed at a file or ZEO URI.

5. **`pwncat/commands`** — the interactive REPL layer. One `Command` class per file, subclassing `CommandDefinition`; its `ARGS` dict (argparse kwargs plus a tab-completion type) alone drives argument parsing, tab-completion, and syntax highlighting — there is no separate grammar to maintain. `CommandParser` loads every command the same way modules are loaded (`pkgutil.walk_packages`). Module-facing commands (`use`, `run`, `search`) bridge into the module system through `Session.run`/`find_module`/`register_fact`, resolving a bare module name against `<platform>.name` then `agnostic.name`.

### Sharp edges worth knowing before touching related code
- Connection-string parsing (`Command.CONNECTION_PATTERN`) and its validation/implant-reconnect logic is duplicated between `__main__.py` and `commands/connect.py` — a fix in one usually needs mirroring in the other.
- `Linux.Popen`'s delimiter framing has no checksum or escaping; it relies on a 10-character random string not colliding with real command output.
- Windows filesystem error handling classifies failures by substring-matching PowerShell's error text (e.g. `"not exist" in str(exc)`), which is brittle across locales/PowerShell versions.
- `Manager`'s own `Listener` wraps accepted sockets itself (`_ssl_wrap`) and hands a plain `Socket` channel straight to the platform, bypassing `Bind`/`SSLBind` entirely — SSL listener behavior lives in two places.
