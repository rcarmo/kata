# Kata Manual

![Kata logo](kata-256.png)

A practical guide to deploying and managing apps with Kata (micro-PaaS on Docker) and its implicit Traefik routing.

## What is Kata?

Kata is a single-file deployment tool that lets you:

- Push an app via git (Piku/Heroku-style) or manage it locally
- Start services with Docker Compose or Docker Swarm
- Get HTTP/HTTPS routing automatically via Traefik labels (no router config needed)

It reads `kata-compose.yaml`, prepares a Docker Compose file, generates Traefik labels, and starts your stack.

## Requirements

- Python 3.12+
- Docker (Compose V2 preferred; V1 `docker-compose` works)
- Optional: Docker Swarm (for stacks and secrets)
- Optional: Traefik v3 on the host (Kata will start or reuse a shared Traefik if none is running)

Notes:

- Kata auto-detects Swarm. Default mode is `swarm` when active, otherwise `compose`.
- Services attach to external Docker network `traefik-proxy`; certificates live in volume `traefik-acme` (created if missing).
- systemd lingering/user services are not required by the current code path.

## Paths, volumes, and app layout

Kata manages per-app folders under a configurable root (defaults shown):

- APP_ROOT: `~/app/APP` — your checked-out code (mounted at `/app`)
- DATA_ROOT: `~/data/APP` — persistent data (mounted at `/data`)
- CONFIG_ROOT: `~/config/APP` — app config (.env, etc.) (mounted at `/config`)
- ENV_ROOT: `~/envs/APP` — runtime environment (e.g., Python venv) (mounted at `/venv`)
- GIT_ROOT: `~/repos/APP` — bare git repo for pushes
- LOG_ROOT: `~/logs/APP` — reserved for logs

Implicit Compose volumes per service

- `app` → bind-mount to `/app` (APP_ROOT/<app>)
- `data` → bind-mount to `/data` (DATA_ROOT/<app>) — use this for databases and persistent state
- `config` → bind-mount to `/config` (CONFIG_ROOT/<app>)
- `venv` → bind-mount to `/venv` (ENV_ROOT/<app>)

Unless you specify your own `volumes`, Kata injects these for each service. If you override volumes, ensure you add back what you need (e.g., reuse `data:/var/lib/postgresql/data` for databases).

## Install and initial setup

1. Place `kata.py` on your host and make it executable.
2. Run `kata setup` — creates the root folders above.
3. (Optional) Enable git-push deploys: `kata setup:ssh ~/.ssh/id_rsa.pub` (adds a forced-command entry to `~/.ssh/authorized_keys`).

## Your app repository

Include at least:

- `kata-compose.yaml` — deployment spec
- Application code at repo root (mounted at `/app`)
- Optional runtime inputs: `requirements.txt`, `package.json`, etc.

Kata supports runtime shortcuts when `image:` is omitted: `runtime: python`, `runtime: nodejs`, `runtime: php`, `runtime: bun`, or `runtime: static` (BusyBox httpd; defaults `PORT=8000`, `DOCROOT=/app`). You can also set `static: true` on a service to auto-wire `kata/static` with sensible defaults.

## Compose specification (kata-compose.yaml)

Top-level keys:

- `environment`: defaults applied to all services (merged; does not override service-specific keys)
- `services`: standard Compose services
- `x-kata-mode`: optional override of `compose` or `swarm`

Notes:

- Environment variables are expanded (e.g., `$APP_ROOT`, `$DATA_ROOT`, `$PORT`).
- Volumes are auto-bound to `/app`, `/config`, `/data`, `/venv` unless you override.
- Setting `static: true` on a service rewrites it to `image: kata/static` and defaults `PORT=8000`, `DOCROOT=/app` (runtime shorthand is also supported).
- A top-level `caddy:` key now triggers a hard error. Remove it and rely on Traefik labels.

Minimal example (Traefik defaults, no host port publishing):

```yaml
# kata-compose.yaml
environment:
  PORT: 8000

services:
  web:
    runtime: python
    command: uvicorn main:app --host 0.0.0.0 --port ${PORT}
    expose:
      - "${PORT}"
```

If you truly need loopback host bindings, force compose mode with `x-kata-mode: compose` and add `ports: ["127.0.0.1:${PORT}:${PORT}"]`.

## Traefik routing

Kata generates Traefik labels automatically. You do not add a `traefik:` block.

Defaults:

- Router name: `<app>-websecure`
- Host rule: `${DOMAIN_NAME:-<app>.localhost}`
- Entry points: `websecure` (with an automatic `web` → `websecure` redirect)
- Service port: first declared `ports`/`expose` entry; otherwise Kata assumes `8000` — ensure the service actually listens there or set `traefik.http.services.<name>.loadbalancer.server.port`
- TLS: enabled; certificates stored in volume `traefik-acme`
- Network: external Docker network `traefik-proxy`

Kata enforces a single shared Traefik per host. It creates/reuses `traefik-proxy` and `traefik-acme` and starts or reuses a container named `kata-traefik`. If you already run Traefik, attach it to that network/volume and Kata will reuse it.

Override via labels on your service, e.g.:

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

CLI helpers:

- `kata config:traefik APP [--json]` — render generated labels/config
- `kata traefik:ls` — list routers/services
- `kata traefik:inspect APP` — show labels per service

## Deployment modes: compose vs swarm

- Default: `swarm` if Docker Swarm is active; otherwise `compose`.
- Override per app: add `x-kata-mode: compose|swarm` or run `kata mode APP compose|swarm` (persists in `.kata-mode`).
- Secrets are Swarm-only; without Swarm, secrets commands will fail.

## Deploying your app

Option A: Git push

- Ensure SSH is set up with `kata setup:ssh ...`.
- Add remote `user@host:APP` and push. Kata clones to `APP_ROOT/APP`, parses `kata-compose.yaml`, generates Traefik labels, selects mode, and starts the stack.

Option B: Manual work tree

- Place code and `kata-compose.yaml` in `APP_ROOT/APP`.
- Deploy by running `kata restart APP` (or `kata git-hook APP` with a synthetic ref update).

Generated file: `APP_ROOT/APP/.docker-compose.yaml` (regenerated on deploy).

## Command reference

- `ls` — list deployed apps (asterisk indicates running)
- `config:stack APP` — show `kata-compose.yaml`
- `config:docker APP` — show generated `.docker-compose.yaml`
- `config:traefik APP` — show generated Traefik labels/config
- `traefik:ls` — list routers/services
- `traefik:inspect APP` — show labels per service
- `restart APP` — restart the app
- `stop APP` — stop the app
- `rm [-w|--wipe] APP` — remove app (and optionally wipe data/config)
- `mode APP [compose|swarm]` — get/set app mode and restart to apply
- `docker ...` — pass-through to Docker CLI (logs, ps, exec, etc.)
- `docker:services STACK` — list services in a Swarm stack
- `ps SERVICE...` — `docker service ps` for Swarm services
- `run SERVICE CMD...` — `docker exec -ti` into a running container
- `secrets:set/ls/rm` — manage Swarm secrets
- `setup` — create Kata root folders
- `setup:ssh FILE|-` — add SSH key for git deploys
- `update` — update `kata.py` from reference URL
- `help` — CLI help

## Logs and troubleshooting

- Compose: `docker compose -f APP_ROOT/APP/.docker-compose.yaml logs -f`
- Swarm: `docker service ps APP_web` then `docker logs <container>`
- Generic: `kata docker logs <container>` (pass-through)

Common issues:

- `caddy:` present: now errors. Remove it and rely on Traefik defaults/labels.
- Port not reachable: check mode (Swarm ignores loopback binds); force compose if needed. Ensure your service declares `ports` or `expose` if Traefik should reach it.
- Traefik missing: start Traefik yourself or let Kata inject the minimal service; ensure `traefik-proxy` and `traefik-acme` exist.
- Secrets error: initialize Swarm or avoid secrets commands.
- Runtime install problems: ensure `requirements.txt` or `package.json` exists; inspect build output.

## Environment variables available to services

Provided to each service unless overridden:

- PUID, PGID
- APP_ROOT, DATA_ROOT, CONFIG_ROOT, ENV_ROOT, GIT_ROOT, LOG_ROOT (app-specific paths)

Merge order (later wins): base → top-level `environment:` → `ENV` / `.env` → service env.

## Uninstalling an app

- Stop and remove: `kata rm APP`
- Add `--wipe` to also remove `DATA_ROOT/APP` and `CONFIG_ROOT/APP`.
