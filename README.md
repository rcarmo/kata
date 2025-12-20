# kata

> Kata (型) means _form / model / pattern_. This project provides a tiny “micro-PaaS” wrapper around Docker (Compose or Swarm) with implicit HTTP routing via Traefik.

## What it does (current implementation)

- Parses an application `kata-compose.yaml` and generates a `.docker-compose.yaml` used for deployment
- Supports either Docker Swarm (`docker stack deploy`) or Docker Compose (`docker compose up -d`) per app (auto‑selects, overridable)
- Implicitly wires HTTP routing through Traefik using generated labels
- Builds lightweight runtime images on‑demand for `runtime: python`, `runtime: nodejs`, `runtime: php`, `runtime: bun`, or static assets.
- Manages per‑app bind‑mounted directories (code, data, config, venv, logs, repos)
- Merges environment variables from multiple sources and injects them into each service
- Provides simple git push deployment hooks (`git-receive-pack` / `git-hook`)
- Offers helper commands for secrets (Swarm only), mode switching, and Traefik inspection

## Requirements

Mandatory:

- **Docker** 20.10+ (Swarm optional; if inactive, Compose mode is used)
- **Python** 3.12+ (to run `kata.py`)

Optional (HTTP routing via Traefik):

- **Traefik** v3 on the host (containerized). Kata will create or reuse the external Docker network `traefik-proxy` and the volume `traefik-acme` for certificate storage, and will start a shared Traefik container (`kata-traefik`) if none is running.

> systemd / Podman are **not** required by the current code path (earlier design notes referenced them).

Tested on Debian 12/13, recent Ubuntu, and macOS with Docker Desktop.

## Traefik Routing

Traefik is **opt-in**. If you do not provide a `traefik:` block, Kata will not add labels or inject Traefik. Add a `traefik` block to the root of your `kata-compose.yaml` to enable routing.

You can always add Traefik labels manually on any service; the `traefik` block is just a convenience that generates a consistent set of labels for one target service.

Key defaults (when `traefik` is provided):

- Router name: `<app>`
- Host rule: `traefik.host` (required)
- Entry points: `websecure` by default; `web` → `websecure` redirect only if you set `enable_http_redirect`
- Service: `traefik.service` (defaults to the first service listed if omitted); declare `ports`/`expose` and set `traefik.port` if it differs from the declared port (defaults to 8000 if unset)
- TLS: enabled by default when using `websecure`; certificates stored in the external volume `traefik-acme`
- Network: only the Traefik-targeted service is attached to the external Docker network `traefik-proxy`; other services are untouched

Kata can start or reuse a shared Traefik container named `kata-traefik` on the `traefik-proxy` network with the `traefik-acme` volume. If you already run Traefik, keep it attached to that network/volume and Kata will reuse it.

### Customizing

You can override host/entrypoint/redirect/port via labels under your service (Compose syntax), e.g.:

```yaml
services:
  web:
    labels:
      traefik.http.routers.websecure.rule: Host(`app.example.com`)
      traefik.http.routers.websecure.entrypoints: websecure
      traefik.http.services.web.loadbalancer.server.port: "5000"
```

#### Service with no exposed port (not routed)

If a service does not declare `ports` or `expose`, Traefik will not be able to reach it. This is fine for workers/cron jobs:

```yaml
services:
  worker:
    image: busybox
    command: ["sh", "-c", "echo worker started; sleep infinity"]
    # No ports/expose → not routable via Traefik
```

### Inspecting Traefik config

- `kata config:traefik <app> [--json]` — render generated labels and router/service rules
- `kata traefik:ls` — list routers/services for the generated stack
- `kata traefik:inspect <app>` — show labels per service

### Static runtime

Use `runtime: static` to serve a directory via BusyBox `httpd` (image `kata/static`). Defaults: `PORT=8000`, `DOCROOT=/app`.

### Application Structure

Paths are rooted at `KATA_ROOT` (default: `$HOME`). The current directory names (note: singular `app/`) are:

- Code: `$KATA_ROOT/app/<app>`
- Data: `$KATA_ROOT/data/<app>`
- Config: `$KATA_ROOT/config/<app>` (place `ENV` or `.env` here to override variables)
- Virtual env / runtime state: `$KATA_ROOT/envs/<app>`
- Logs: `$KATA_ROOT/logs/<app>`
- Git bare repos: `$KATA_ROOT/repos/<app>`

Generated file: `.docker-compose.yaml` inside the app code directory (regenerated each deploy).

## Traefik Sample Labels

Add only the labels you need; Kata supplies sensible defaults.

```yaml
services:
  web:
    labels:
      traefik.http.routers.websecure.rule: Host(`app.example.com`)
      traefik.http.routers.websecure.entrypoints: websecure
      traefik.http.routers.websecure.tls: "true"
      traefik.http.middlewares.web-redirect.redirectscheme.scheme: https
      traefik.http.routers.websecure.middlewares: web-redirect
      traefik.http.services.web.loadbalancer.server.port: "5000"
```

## Environment Variables

Merged from (later sources override earlier):

1. Base: `PUID`, `PGID`, and per‑app root paths (`APP_ROOT`, `DATA_ROOT`, `ENV_ROOT`, `CONFIG_ROOT`, `GIT_ROOT`, `LOG_ROOT`)
2. Top‑level `environment:` mapping in `kata-compose.yaml` (optional)
3. `ENV` or `.env` file in the app’s config directory
4. Service‑level `environment` entries

Compose list form (`["KEY=VALUE", "BARE_KEY"]`) is normalized; bare keys default to empty string.

Recommended to set:

- `PORT` (service listen port, especially for reverse proxying)
- `BIND_ADDRESS` (default `127.0.0.1` if omitted in your own config logic)
- `DOMAIN_NAME` (for host matchers / TLS)

Declare `ports` or `expose` on the service you want Traefik to reach; Kata no longer adds these automatically. If you prefer a different target, set `traefik.service` (and `traefik.port` if it differs from the declared port).

Automatically injected into each service unless already set: the base variables above.

For more details on Traefik labels, see the [Traefik reference](https://doc.traefik.io/traefik/routing/routers/).

### Troubleshooting Traefik

- Inspect generated config for an app:

```bash
kata config:traefik <app> --json
```

- List routers/services for your stack:

```bash
kata traefik:ls
```

- Typical errors:
  - “PORT not set”: ensure your service declares `ports`/`expose` and the app listens there (or set `traefik.http.services.<name>.loadbalancer.server.port`; Kata assumes 8000 if nothing is specified).
  - Traefik not running: start it or allow Kata to inject the minimal service; ensure the `traefik-proxy` network exists.
  - DNS/TLS: verify your host rule matches a reachable domain and that ports 80/443 are open to the world.

## Examples

Each example declares a `PORT` and exposes it on the `web` service so Traefik can route to it. By default the first service (`web`) is targeted; set `traefik.service`/`traefik.port` if you need a different mapping.

- [docs/examples/minimal-python](docs/examples/minimal-python) — FastAPI on the Python runtime
- [docs/examples/minimal-nodejs](docs/examples/minimal-nodejs) — Express on the Node.js runtime
- [docs/examples/minimal-php](docs/examples/minimal-php) — Built-in PHP server on the PHP runtime
- [docs/examples/minimal-bun](docs/examples/minimal-bun) — Bun server on the Bun runtime
- [docs/examples/static-site](docs/examples/static-site) — BusyBox httpd with the static runtime
- [docs/examples/generic-whoami](docs/examples/generic-whoami) — Stock image path without runtime helpers

## Compose vs Swarm Modes

Default per host state:

- Swarm active → deploy via `docker stack deploy`
- Swarm inactive → deploy via `docker compose up -d`

Override per app:

```yaml
x-kata-mode: compose # or swarm
```

Or with CLI:

```bash
kata mode <app>          # show
kata mode <app> compose  # set & restart
kata mode <app> swarm
```

Helper file `.kata-mode` in the app root persists the selection.

### Runtime Images

If a service defines:

```yaml
services:
  web:
    runtime: python # or nodejs | php | bun | static
    command: ["python", "-m", "app"]
```

Kata will build (once) or reuse a `kata/<runtime>` image from an internal Dockerfile, bind‑mount app/config/data/venv, and run runtime-specific prep:

- python: create venv + `pip install -r requirements.txt`
- nodejs: `npm install`
- php: `composer install --no-dev --optimize-autoloader`
- bun: `bun install`
- static: no prep; use BusyBox httpd

If you supply `image:` yourself, no runtime automation runs.

### Secrets (Swarm only)

Commands:

```bash
kata secrets:set NAME=VALUE   # NAME=@file, NAME=- (stdin), or just NAME (prompt)
kata secrets:ls
kata secrets:rm NAME
```

They are disabled (with a warning) when Swarm is inactive.

### Git Deployment

Two internal commands (`git-receive-pack` / `git-upload-pack`) plus the `git-hook` are used when you push to a bare repo under `$KATA_ROOT/repos/<app>`. The post‑receive hook triggers `git-hook` which runs `do_deploy`.

You can also manually trigger deployment by piping a synthetic ref update:

```bash
echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook <app>
```

### CLI Overview

Selected commands (run `kata help` for full output):

| Command                      | Purpose                               |
| ---------------------------- | ------------------------------------- |
| setup                        | Create root directories               |
| ls                           | List apps & running state             |
| restart / stop / rm          | Lifecycle management                  |
| mode                         | Get/set deploy mode                   |
| config:stack                 | Show original `kata-compose.yaml`     |
| config:docker                | Show generated `.docker-compose.yaml` |
| config:traefik               | Show generated Traefik labels/config  |
| traefik:ls / traefik:inspect | Inspect routers/services and labels   |
| secrets:\*                   | Manage Swarm secrets                  |
| docker ...                   | Passthrough to `docker`               |
| docker:services / ps         | Inspect Swarm/Compose processes       |
| run <service> <cmd...>       | Exec into a running container         |
| update                       | (WIP) self‑update script              |

---

Feedback / issues welcome. This README tracks the **current code** in `kata.py`; if something here is missing in code, file a bug.
