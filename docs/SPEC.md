# Kata: Specification

![Kata logo](kata-256.png)

> This document reflects **what `kata.py` implements today** and the **near-term design direction**. It is the single, consolidated spec for Kata; where it disagrees with `kata.py`, the code is authoritative and this document should be corrected.

## Overview

Kata is a single-file (`kata.py`, Python 3.12+) micro-PaaS — a Piku-style refactor — that deploys applications from git pushes (or manual triggers) onto Docker, using either **Swarm stacks** or **Compose**, with optional implicit HTTP(S) routing through **Traefik**.

The pipeline is: parse a `kata-compose.yaml` → merge environment → ensure runtime images → generate a `.docker-compose.yaml` → deploy via Swarm/Compose → (optionally) generate Traefik labels for one target service.

Key properties:

- Single Python script, no external database, only `click` + `pyyaml` runtime deps
- Bind-mounted host directories under `$KATA_ROOT` instead of named volumes (unless the user supplies their own `volumes:` mapping)
- On-demand runtime image bootstrap for `python`, `nodejs`, `php`, `bun`, and `static`
- Deterministic environment merging with per-service overrides
- Opt-in Traefik routing via a `traefik:` block (generates consistent labels for one service)
- Git-push deployment via internal `git-*` commands and forced `authorized_keys` commands
- Per-app deploy mode (`swarm`/`compose`) auto-selected from host state, overridable

**Non-goals (current state):** horizontal scaling abstractions beyond Docker/Swarm primitives, declarative build phases, systemd/Podman orchestration, multi-node scheduling beyond Swarm's native behavior, integrated log aggregation, cloud/DNS automation.

> **Removed:** Caddy integration is gone. A `caddy:` top-level key is now a hard error (`kata.py` exits with a message pointing to Traefik). systemd/Podman quadlet design notes from earlier drafts are not implemented.

## Core Architecture (Implemented)

### Components

1. **Git-based deployment**
   - Bare repo under `$KATA_ROOT/repos/<app>`
   - `post-receive` hook invokes `kata.py git-hook <app>`
   - First push clones the bare repo into `app/<app>`; the hook triggers `do_deploy()` which fetches/resets the working tree, regenerates config, and deploys
2. **Container orchestration**
   - Docker Swarm (`docker stack deploy <app> --compose-file … --resolve-image=never --prune`) when Swarm is active
   - Docker Compose (`docker compose up -d --remove-orphans`) otherwise
   - Per-app mode selectable via `kata mode <app> [compose|swarm]`, `x-kata-mode:` key, or persisted `.kata-mode` file
3. **Runtime images**
   - On-demand build of `kata/<runtime>` from an embedded Dockerfile when a service declares `runtime: python|nodejs|php|bun|static`
   - Injects default bind volumes: `app`, `config`, `data`, `venv`
   - Runtime-specific prep on deploy (venv/pip, npm, composer, bun install; static needs none)
4. **Environment merging**
   - Base (paths + `PUID`/`PGID`) → top-level `environment:` → config file `ENV`/`.env` → service environment (list or mapping), with service-defined keys winning
5. **Traefik integration (opt-in)**
   - A top-level `traefik:` block generates labels for one target service and attaches it to the external `traefik-proxy` network
   - Kata ensures/reuses a shared `kata-traefik` container, the `traefik-proxy` network, and the `traefik-acme` volume
6. **Secrets (Swarm only)**
   - Thin passthrough to `docker secret` (`secrets:set|ls|rm`), gated by Swarm detection (warns and no-ops otherwise)

## Directory Structure

Rooted at `$KATA_ROOT` (default `$HOME`). Note the **singular** directory names:

| Path | Purpose | Mount |
|------|---------|-------|
| `app/<app>` | Working tree (checked-out code) | `/app` |
| `data/<app>` | Persistent data | `/data` |
| `config/<app>` | Config overrides (`ENV` / `.env`) | `/config` |
| `envs/<app>` | Virtual env / runtime state | `/venv` |
| `logs/<app>` | Reserved (not actively written by kata.py) | `/logs` |
| `repos/<app>` | Bare git repo (push target) | — |

Generated per deployment: `app/<app>/.docker-compose.yaml` (regenerated each deploy). Per-app mode persisted in `app/<app>/.kata-mode`.

## Configuration Format (`kata-compose.yaml`)

A **Compose-like** YAML. Kata reads a subset and passes the rest through to the generated `.docker-compose.yaml`.

Recognized top-level keys:

- `environment:` — mapping merged into every service (optional)
- `services:` — service definitions (Compose-compatible, plus Kata extensions below)
- `traefik:` — optional routing block (see below); consumed and stripped before generation
- `volumes:` — optional; if omitted, Kata injects four bind-mount volumes (`app`, `config`, `data`, `venv`)
- `x-kata-mode: compose|swarm` — optional per-app deploy mode override

A top-level `caddy:` key is rejected with an error.

### Service extensions

- `runtime: python|nodejs|php|bun|static` — Kata supplies `image: kata/<runtime>` and default mounts, and runs runtime prep. Deleted from the generated service.
- `static: true` (shorthand) — sets `image: kata/static`, defaults `PORT=8000`, `DOCROOT=/app`.
- If you supply `image:` yourself, **no** runtime automation runs.
- If a service omits `volumes:`, Kata injects `["app:/app", "config:/config", "data:/data", "venv:/venv"]`. Custom volumes are honored (with a warning).
- A service with neither `image` nor `runtime` and no `command` triggers a warning and is skipped for command handling.

### Environment forms

Service `environment:` may be a mapping (`KEY: value`) or a list (`["KEY=VALUE", "BARE_KEY"]`). Lists are normalized to a mapping; bare keys default to empty string. Env placeholders (`$VAR`) are expanded across the loaded structure.

### Ports / exposure

Kata does **not** auto-add `ports`/`expose`. Declare them explicitly on any service you want reachable (directly or via Traefik).

## Traefik Routing (opt-in)

Provide a `traefik:` block to generate a consistent set of labels for **one** target service:

```yaml
traefik:
  host: app.example.com        # required (traefik.host)
  service: web                 # optional; defaults to first service listed
  port: 8000                   # optional; defaults to declared port, else 8000
  enable_http_redirect: false  # optional; web → websecure redirect
```

Behavior:

- Router name: `<app>`; host rule from `traefik.host` (required)
- Entry points: `websecure` by default; `web → websecure` redirect only if `enable_http_redirect`
- TLS enabled by default on `websecure`; certs stored in external volume `traefik-acme`
- Only the targeted service is attached to the external `traefik-proxy` network; other services are untouched
- If the target service uses `network_mode`, label injection is skipped (with a warning)

You can always set Traefik labels manually on a service instead of (or in addition to) the `traefik:` block. Kata ensures/reuses a shared `kata-traefik` container; if you already run Traefik on the `traefik-proxy` network with the `traefik-acme` volume, Kata reuses it.

## Supported Runtimes

| Runtime | Base | Prep on deploy |
|---------|------|----------------|
| `python` | Debian trixie-slim | create `/venv`, `pip install -r requirements.txt` |
| `nodejs` | Debian trixie-slim | `npm install` |
| `php` | Debian trixie-slim | `composer install --no-dev --optimize-autoloader` |
| `bun` | Debian trixie-slim | `bun install` |
| `static` | BusyBox `httpd` (`kata/static`) | none; serves `DOCROOT` (default `/app`) on `PORT` (default `8000`) |

Images are built once as `kata/<runtime>` and reused. Rebuild via `runtime:rebuild[-all]`; remove via `runtime:clean`.

## Environment Merging Rules

Order of precedence (last wins):

1. Base variables: `PUID`, `PGID`, and per-app root paths (`APP_ROOT`, `DATA_ROOT`, `ENV_ROOT`, `CONFIG_ROOT`, `GIT_ROOT`, `LOG_ROOT`)
2. Top-level `environment:` in `kata-compose.yaml`
3. `ENV` or `.env` in `config/<app>`
4. Service-level `environment` (list or mapping)

During normalization, list form is converted to a mapping and base variables are added to a service only if not already defined there.

## Git / SSH Flow

- `setup:ssh <pubkey>` appends an `authorized_keys` entry with a forced command referencing `kata.py`
- `git-receive-pack` / `git-upload-pack` (hidden) are passthroughs invoked via `git-shell`; `git-receive-pack` initializes the bare repo and installs the `post-receive` hook on first use
- After a push, the hook pipes ref updates to `git-hook <app>`, which clones on first deploy and calls `do_deploy(app, newrev=…)`

Manual trigger:

```bash
echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook <app>
```

## CLI (Implemented Commands)

| Command | Summary |
|---------|---------|
| `setup` | Create root directory skeleton |
| `setup:ssh <pubkey>` | Register SSH key with forced command (`-` for stdin) |
| `ls` | List apps; `*` marks any app with a running `‹app›-*` container |
| `config:stack <app>` | Show original `kata-compose.yaml` |
| `config:docker <app>` | Show generated `.docker-compose.yaml` |
| `config:traefik <app> [--json]` | Show generated Traefik labels/config |
| `traefik:ls <app>` | List routers/services for the stack |
| `traefik:inspect <app>` | Show labels per service |
| `traefik:dashboard [--port/--bind/--web/--websecure/--off/--replace]` | Restart shared Traefik with/without dashboard |
| `restart <app>` | Stop then start the whole app |
| `stop <app>` | Stop the app (stack rm / compose down) |
| `rm <app> [--force] [--wipe]` | Remove app; `--wipe` also deletes data/config (root-container wipe of bind mounts) |
| `mode <app> [compose\|swarm]` | Get/set deploy mode (restarts on change) |
| `secrets:set\|ls\|rm` | Manage Swarm secrets (Swarm only) |
| `runtime:rebuild-all` / `runtime:rebuild <rt>` / `runtime:clean` | Manage runtime images |
| `docker …` | Passthrough to `docker` |
| `docker:services <stack>` | `docker stack services` |
| `ps <app> [service…]` | Tasks for an app/services (Swarm `service ps`, else `compose ps`) |
| `run <service> <cmd…>` | `docker exec -ti <service> <cmd>` |
| `scp …` | Passthrough to `scp` |
| `update` | Self-update `kata.py` from the raw GitHub source (writes `.backup`) |
| `help` | Show CLI help |
| `git-hook` / `git-receive-pack` / `git-upload-pack` | Internal (hidden) |

## Deployment Sequence (Actual)

1. Git push triggers `git-hook` (first push also clones into `app/<app>`)
2. Update working tree: `git fetch`, `git reset --hard <newrev>`, submodule init/update
3. `ensure_shared_traefik()`
4. `parse_compose`: merge env → build runtime image(s) if needed → apply Traefik labels → write `.docker-compose.yaml`
5. Record mode (`x-kata-mode` overrides host autodetect) and `do_start` via Swarm or Compose

## Security (Current)

- SSH forced-command restrictions via `authorized_keys`
- Docker isolation only (no systemd sandboxing / Podman)
- Traefik TLS automation via standard ACME (`traefik-acme` volume) when `websecure` is used
- `rm --wipe` runs a root BusyBox container to delete root-owned files on bind mounts before host-side cleanup; semantics differ under rootless/userns-remap Docker

## Logging (Current)

- Kata prints to stdout/stderr
- Container logs via `docker` / `kata docker logs …`; no integrated aggregation. `logs/<app>` is reserved but not written by kata.py.

---

## Design Direction: SSH-friendly per-container operations

> **Status: proposed (not yet implemented).** Captured here to keep the single-file design honest about where it's going.

### Problem

Operating Kata over SSH today is awkward for **individual containers**, especially under **Swarm**:

- `restart` only restarts the **whole app** (stop + start). There is no per-service restart.
- `run <service> <cmd>` and `ps` assume the caller already knows the exact container/service name.
- Swarm assigns **random task/container names** (`<stack>_<service>.<slot>.<id>`), so a human over SSH cannot easily guess the name to target.
- `ls` only reports app-level running state (matches `‹app›-*`), not per-service container identity.

### Goals

1. **Autodetect** the concrete container(s) backing an `(app, service)` pair in both modes:
   - Compose: containers labeled `com.docker.compose.project=<app>` / `…compose.service=<service>`
   - Swarm: tasks/containers labeled `com.docker.stack.namespace=<app>` and `com.docker.swarm.service.name=<app>_<service>`, including replicas across nodes
2. **Per-service restart** that does the right thing per mode:
   - Compose: `docker compose -f … restart <service>` (or `up -d` for the single service)
   - Swarm: `docker service update --force <app>_<service>` (rolling restart without re-deploying the stack)
3. **Discoverability**: list services/containers for an app so an SSH user can pick a target without knowing random names.
4. Keep everything **single-file** and dependency-free (shell out to `docker`, parse `--format` output).

### Proposed CLI surface

| Command | Behavior |
|---------|----------|
| `restart <app> [service…]` | No service → whole-app restart (current behavior). One or more services → per-service restart, mode-aware. |
| `services <app>` | List logical services for an app with desired/running replica counts and mode (wraps `docker stack services` / `compose ps --services`). |
| `containers <app> [service]` | Resolve and print concrete container IDs/names/nodes for an app or one service (the autodetect primitive). |
| `run <app> <service> [--index N] <cmd…>` | Resolve the container for `(app, service)` (first/replica `N`) and `docker exec` into it — no manual container name needed. |

Notes:

- `run` would change from taking a raw container name to taking `(app, service)` and resolving it; the raw-name form can remain as a fallback.
- Resolution helper (e.g. `resolve_containers(app, service=None) -> list[ContainerRef]`) becomes the shared primitive for `run`, `restart <service>`, `containers`, and `ps`.
- Under Swarm, prefer `docker service update --force` for restarts (cluster-aware, rolling) over killing individual task containers; reserve container-level `exec` for `run`/debugging.
- All resolution should be label-based (stable) rather than name-prefix matching, to survive Swarm's random task IDs.

### Out of scope (for now)

Multi-node SSH fan-out, log streaming aggregation, and replica scaling commands remain non-goals; Swarm handles scheduling natively.

---

This document should be updated alongside code changes; discrepancies mean the code is authoritative.
