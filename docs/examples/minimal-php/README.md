# Minimal PHP example

A tiny PHP app served by the built-in PHP server using Kata’s `runtime: php` shortcut.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block (HTTP-only in this example)
- `public/index.php` — single endpoint returning JSON
- `composer.json` — present so the runtime hook can run `composer install`

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

- The runtime hook runs `composer install --no-dev --optimize-autoloader`; you can add dependencies to `composer.json` as needed.
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
