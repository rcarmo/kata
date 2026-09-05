# Python app with internal DB network

Shows how to keep a database on an internal network while letting Traefik reach the web service.

## Files

- `kata-compose.yaml` — web service on Traefik + internal networks; Postgres only on the internal network, data stored in the shared `data` volume (DATA_ROOT/<app>)
- `app.py` — FastAPI app returning DB connection info (no migrations/ORM)
- `requirements.txt` — runtime dependencies

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

Notes

- The web service joins both the internal network and the `traefik-proxy` network so Traefik can reach it.
- The database only joins the internal network, so it is not reachable externally.
- Adjust credentials in the `environment` block as needed; this example uses defaults for simplicity.
