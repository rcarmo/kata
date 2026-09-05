# Minimal Node.js example

A tiny Express app deployed with Kata using the `runtime: nodejs` shortcut.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block (HTTP-only in this example)
- `app.js` — Express app with a single endpoint
- `package.json` — npm manifest; dependencies are installed by the runtime hook

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

- You do not need host port mappings; Traefik shares the `traefik-proxy` Docker network with the service.
- Edit the host rule via Traefik labels if you want a real domain instead of `<app>.localhost`.
