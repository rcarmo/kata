# Static site example

A static HTML site served by Kata’s `runtime: static` BusyBox httpd image.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block (HTTP-only in this example)
- `public/index.html` — sample static page

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

- `DOCROOT` can be adjusted in `kata-compose.yaml` if you prefer a different folder.
- To change hostnames, edit the `traefik.http.routers.site-alt.rule` label (it uses `Host(`site.localhost`) || Host(`alias.localhost`)` by default).
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
