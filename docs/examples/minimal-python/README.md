# Minimal Python example

A tiny FastAPI app deployed with Kata and Traefik.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block
- `app.py` — FastAPI app with a single endpoint
- `requirements.txt` — Python deps installed into `/venv` by the runtime hook

## Deploying this example

Follow the [first-deployment instructions](../../INSTALL.md#first-deployment),
copying this directory into a separate Git repository and pushing it to the
configured Kata account. Edit `kata-compose.yaml` before pushing: choose a mode,
hostname and appropriate credentials. `restart` requires an already generated
`.docker-compose.yaml`; copying this folder into `app/APP` is not enough.

The `.localhost` hostnames are placeholders, not automatically trusted HTTPS
endpoints. For local testing select `entrypoints: [web]`, `tls: false` and disable
HTTP redirects. Public HTTPS needs real DNS, ACME configuration and reachable
ports. See the [manual](../../MANUAL.md#routing).

Notes:

- If you’re using a real domain, set your host rule via Traefik labels or a `traefik:` block.
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
