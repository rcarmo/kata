# Minimal Bun example

A tiny JSON endpoint powered by Bun using Kata’s `runtime: bun` shortcut.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block
- `index.ts` — Bun server with a single route
- `package.json` — present so the runtime hook can run `bun install`

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

- The runtime hook runs `bun install`; add any dependencies to `package.json`.
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
