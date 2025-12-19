# Installation Guide for Kata

Kata is a lightweight wrapper around Docker (Compose or Swarm) with implicit Traefik routing. These steps target a fresh Linux host or macOS with Docker Desktop.

## Prerequisites

- Docker 20.10+ (Swarm optional; Compose is used if Swarm is inactive)
- Python 3.12+
- Git, curl

Optional but recommended for HTTPS:

- Traefik v3 (containerized). Kata expects or will create:
  - external Docker network `traefik-proxy`
  - Docker volume `traefik-acme` for certificates

## Install Kata

1. Download the script (adjust URL as needed):

```bash
curl -o kata.py https://raw.githubusercontent.com/piku/kata/master/kata.py
chmod +x kata.py
mkdir -p ~/bin
mv kata.py ~/bin/
```

Ensure `~/bin` is on your `PATH` (e.g., add `export PATH="$HOME/bin:$PATH"` to your shell rc file).

2. Run the initial setup to create directories under `~/.kata` (or `$KATA_ROOT`):

```bash
kata setup
```

3. (Optional) Add your SSH public key so you can deploy via `git push`:

```bash
kata setup:ssh ~/.ssh/id_rsa.pub
```

## Provision shared Traefik (once per host)

Kata enforces a single Traefik per host. It will create `traefik-proxy` / `traefik-acme` and start or reuse a container named `kata-traefik` automatically when you deploy. If you prefer to start it yourself (or run a custom Traefik), launch it attached to the shared network/volume:

```bash
docker network create traefik-proxy || true
docker volume create traefik-acme || true
docker run -d --name kata-traefik --restart unless-stopped \
	--network traefik-proxy \
	-p 80:80 -p 443:443 \
	-v /var/run/docker.sock:/var/run/docker.sock:ro \
	-v traefik-acme:/etc/traefik \
	traefik:v3.6.5 \
	--providers.docker=true \
	--providers.docker.exposedbydefault=false \
	--entrypoints.web.address=:80 \
	--entrypoints.websecure.address=:443 \
	--certificatesresolvers.default.acme.email=${KATA_ACME_EMAIL:-admin@example.com} \
	--certificatesresolvers.default.acme.storage=/etc/traefik/acme.json \
	--certificatesresolvers.default.acme.httpchallenge.entrypoint=web
```

If you already run Traefik, keep it attached to `traefik-proxy` and `traefik-acme` and Kata will reuse it; otherwise it will start `kata-traefik` for you during deploy.

## Deploy your first app

1. Copy an example app:

```bash
cp -a docs/examples/minimal-python "$HOME/app/hello"
```

2. Deploy:

```bash
kata restart hello
```

3. Browse to `https://hello.localhost/` (self‑signed locally). If using a real domain, set `DOMAIN_NAME` in your `kata-compose.yaml` and ensure DNS points to this host.

## Troubleshooting

- `kata config:traefik <app> --json` to inspect generated labels
- `kata traefik:ls` to see routers/services
- Confirm Docker network `traefik-proxy` exists and Traefik is attached to it
- If ports are missing, add `expose` or `ports` to the service so Traefik has a target port
