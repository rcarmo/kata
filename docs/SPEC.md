# Kata: Specification

![Kata logo](kata-256.png)

> This document reflects **what `kata.py` implements today** and the **near-term design direction**. It is the single, consolidated spec for Kata; where it disagrees with `kata.py`, the code is authoritative and this document should be corrected.

## Deployment model

Kata is a single-file (`kata.py`, Python 3.12+) micro-PaaS — a Piku-style refactor — that deploys applications from git pushes (or manual triggers) onto Docker, using either **Swarm stacks** or **Compose**, with optional implicit HTTP(S) routing through **Traefik**.

The pipeline is: parse a `kata-compose.yaml` → merge environment → ensure runtime images → generate a `.docker-compose.yaml` → generate optional Traefik labels → deploy via Swarm/Compose.

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
   - Thin passthrough to `docker secret` (`secrets:set|ls|rm`), gated by Swarm detection (creation fails without a manager; legacy list/removal preconditions warn)

## Directory Structure

Rooted at `$KATA_ROOT` (default `$HOME`). Note the **singular** directory names:

| Path | Purpose | Mount |
|------|---------|-------|
| `app/<app>` | Working tree (checked-out code) | `/app` |
| `data/<app>` | Persistent data | `/data` |
| `config/<app>` | Config overrides (`ENV` / `.env`) | `/config` |
| `envs/<app>` | Virtual env / runtime state | `/venv` |
| `logs/<app>` | Reserved (not actively written by kata.py) | no default mount |
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
- On the no-`image` path, if a service omits `volumes:`, Kata injects `["app:/app", "config:/config", "data:/data", "venv:/venv"]`. Custom volumes are honored (with a warning).
- A non-static service without `command` triggers a warning and skips environment normalisation.

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
  port: 8000                   # optional; defaults to 8000; not inferred
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
3. `ENV`, then `.env`, in `config/<app>` (both are loaded if present)
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
| `restart <app> [service…]` | Whole-app restart, or per-service (mode-aware); `--logs/-l` follows service logs |
| `stop <app>` | Stop the app (stack rm / compose down) |
| `services <app>` | List an app's services (mode-aware) |
| `containers <app> [service]` | Resolve concrete container IDs/names (label-based) |
| `logs <app> [service] [-f] [--tail N]` | Tail app/service logs (mode-aware) |
| `rm <app> [--force] [--wipe]` | Remove app; `--wipe` also deletes data/config (root-container wipe of bind mounts) |
| `mode <app> [compose\|swarm]` | Get/set deploy mode (restarts on change) |
| `secrets:set\|ls\|rm` | Manage Swarm secrets (Swarm only; names are validated conservatively) |
| `runtime:rebuild-all` / `runtime:rebuild <rt>` / `runtime:clean` | Manage runtime images |
| `docker …` | Passthrough to `docker` |
| `docker:services <stack>` | `docker stack services` |
| `ps <app> [service…]` | Tasks for an app/services (Swarm `stack ps` or selected `service ps`, else `compose ps`) |
| `run <app> <service> [--index N] <cmd…>` | Autodetect the container and `docker exec -i` (plus `-t` for terminals) into it |
| `scp …` | Passthrough to `scp` |
| `update [--force] [--no-restart]` | Self-update `kata.py` from upstream: follows redirects, validates the download compiles, writes a `.backup`, replaces atomically, and re-execs |
| `help` | Show CLI help |
| `git-hook` / `git-receive-pack` / `git-upload-pack` | Internal (hidden) |

## Deployment Sequence (Actual)

1. Git push triggers `git-hook` (first push also clones into `app/<app>`)
2. Update working tree: `git fetch`, `git reset --hard <newrev>`, submodule init/update
3. `ensure_shared_traefik()`
4. `parse_compose`: merge env → build runtime image(s) if needed → apply Traefik labels → write `.docker-compose.yaml`
5. Record mode (`x-kata-mode` overrides host autodetect) and `do_start` via Swarm or Compose

For full-app restarts in Swarm mode, Kata waits for `docker stack rm` teardown to finish before redeploying. If services or stack networks do not drain within the timeout, restart aborts rather than redeploying into a half-removed stack.

## Security (Current)

- SSH forced-command restrictions via `authorized_keys`
- Docker isolation only (no systemd sandboxing / Podman)
- Traefik TLS automation via standard ACME (`traefik-acme` volume) when `websecure` is used
- `rm --wipe` runs a root BusyBox container to delete root-owned files on bind mounts before host-side cleanup; semantics differ under rootless/userns-remap Docker

## Logging (Current)

- Kata prints to stdout/stderr
- Container logs via `kata logs APP [SERVICE]` or Docker passthrough; no integrated aggregation. `logs/<app>` is reserved but not written by kata.py.

---

## SSH-friendly per-container operations

> **Status: implemented.**

### Problem

Operating Kata over SSH for **individual containers** was awkward, especially under **Swarm**, which assigns **random task/container names** (`<stack>_<service>.<slot>.<id>`). A common manual workaround was:

```makefile
deploy: deploy-production
	ssh -t kata@$(PRODUCTION_SERVER) docker service update --force $(APP_NAME)_builder
	ssh -t kata@$(PRODUCTION_SERVER) docker service logs --tail 0 -f $(APP_NAME)_builder
```

That now collapses to one line:

```makefile
deploy: deploy-production
	ssh -t kata@$(PRODUCTION_SERVER) restart $(APP_NAME) builder --logs
```

### Resolution primitive

`resolve_containers(app, service=None) -> list[{id, name, status}]` resolves the concrete local containers backing an `(app[, service])` pair using **Docker labels** (not name-prefix matching), so it survives Swarm's random task IDs:

- Compose: `com.docker.compose.project=<app>` (+ `com.docker.compose.service=<service>`)
- Swarm: `com.docker.stack.namespace=<app>` (+ `com.docker.swarm.service.name=<app>_<service>`)

This primitive backs `run` and `containers`.

### CLI surface

| Command | Behavior |
|---------|----------|
| `restart <app>` | Whole-app restart (stop + start), as before. |
| `restart <app> <service...> [--logs]` | Per-service restart: Swarm → `docker service update --force <app>_<service>` (rolling); Compose → `docker compose restart <service...>`. `--logs/-l` follows the last service's logs afterward. |
| `services <app>` | List logical services for an app (Swarm `stack services`, else `compose ps`). |
| `containers <app> [service]` | Resolve and print concrete container IDs/names/status (the autodetect primitive). |
| `logs <app> [service]` | Tail logs, mode-aware (`-f/--follow`, `--tail`). Swarm requires a service; Compose accepts app-wide or per-service. |
| `run <app> <service> [--index N] <cmd...>` | Resolve the container for `(app, service)` (replica `N`) and `docker exec -i` (plus `-t` for terminals) into it. Fails when no local container resolves; use explicit `docker exec` passthrough for raw names. This avoids accidentally executing in an unrelated container. |

Under Swarm, restarts use `docker service update --force` (cluster-aware, rolling) rather than killing individual task containers; container-level `exec` is reserved for `run`/debugging.

### Out of scope (for now)

Multi-node SSH fan-out, log aggregation, and replica scaling commands remain non-goals; Swarm handles scheduling natively.

---

This document should be updated alongside code changes; discrepancies mean the code is authoritative.

## Failure handling and verification

Lifecycle helpers return booleans where documented; CLI wrappers fail non-zero
for checked operations. `checked_call` preserves command failures for SSH/Make.
Legacy warning-only paths remain, so this is not a claim that every CLI error
returns non-zero. Runtime setup/rebuild/cleanup failures are checked.

Git post-receive deployments hold an exclusive per-app `flock` on
`repos/<app>/kata-deploy.lock`. Failed Git preparation stops deployment and deleted
refs are skipped. There is no branch allowlist; the lock covers hooks, not manual
lifecycle commands. Mode changes stop and drain the old deployment before saving
the new mode; a failed new start retains that mode for recovery. Git deployment
recalculates the mode from host state and `x-kata-mode`, rather than preserving a
CLI-only selection indefinitely.

Secret creation validates names before reading input and preserves bytes from
files/stdin. An existing bare path in `NAME=value` still means a file. File/value
errors are not printed verbatim. Secret names allow `[A-Za-z0-9][A-Za-z0-9_.-]*`;
app names allow `[A-Za-z0-9][A-Za-z0-9_-]*` and are rejected rather than rewritten.

Removal rejects redirected per-app paths before teardown, waits for Swarm removal,
and deletes contents (including dotfiles) in a root BusyBox container before host
cleanup. Failures can leave partial deletion, but never report successful removal.
These checks assume a trusted deployment account; Docker access is administrative
access, and concurrent privileged path changes are outside this protection.

Self-update follows HTTPS redirects, checks Python syntax, requires a backup,
preserves permissions and replaces a unique same-directory temporary file
atomically. It re-executes to show help unless `--no-restart` is given. Syntax
validation does not authenticate the downloaded script: upstream is trusted.

### Parser and routing limitations

* Default service mounts are added only on the no-`image` path. Explicit images
  need explicit mounts. `static: true` sets an image early and does not take the
  runtime build/mount path; prefer `runtime: static`.
* A non-static service without `command` skips environment normalisation, even
  when its image has a valid default command. Supplying both `image` and `runtime`
  skips runtime preparation but currently leaves the `runtime` key in output.
* `apply_traefik` defaults its port directly to 8000, not to a declared exposed
  port. Rendering config can run parsing/runtime preparation and create folders.
* Label generation is opt-in, but `do_deploy` calls shared Traefik bootstrap
  unconditionally. No routing block does not guarantee no proxy side effects.
* Swarm deployment requires a manager. Lifecycle fallback tests manager availability,
  while fresh deployment checks active Swarm state. Use an explicit mode on mixed
  hosts. Local images and bind-mounted data are not distributed across nodes.
* Generated YAML is a Compose-like pass-through, not a full schema validator.
  Review it for the selected orchestrator, including Traefik's provider and labels.

### Verification and remaining limits

On 2026-09-05, 27 mocked regression tests passed. An isolated Alpine container with
Compose-compatible labels verified local discovery, non-interactive exec and
failure exit status against Docker 29.1.3, and was removed afterward. The test host
has no Compose plugin and Swarm is inactive; live Compose/Swarm lifecycle tests and
concurrent-push contention tests remain unverified. No production services or host
orchestration configuration were changed.

Runtime tags and apt packages are not pinned. Reproducible builds need a maintained
snapshot/image refresh policy rather than arbitrarily frozen packages. The audit
is not a production-security certification. The development-only HTTP uploader
in `tools/updater.py` must not be exposed on an untrusted network.
