# Generic container example (no runtime)

A minimal example that uses an off-the-shelf image (`traefik/whoami`) without Kata runtime shortcuts.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block

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

- This example demonstrates the `image:` path; no runtime image is built, and no volumes are mounted by default.
- Add your own labels/env/ports as needed for other off-the-shelf images.
