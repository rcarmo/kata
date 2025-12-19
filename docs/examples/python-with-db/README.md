# Python app with internal DB network

Shows how to keep a database on an internal network while letting Traefik reach the web service.

## Files

- `kata-compose.yaml` — web service on Traefik + internal networks; Postgres only on the internal network, data stored in the shared `data` volume (DATA_ROOT/<app>)
- `app.py` — FastAPI app returning DB connection info (no migrations/ORM)
- `requirements.txt` — runtime dependencies

## How to try

1. Ensure Kata is set up on the host: `kata setup`
2. Copy this folder to your Kata apps directory (replace APP with your app name):
   - `cp -a docs/examples/python-with-db "$HOME/app/APP"`
3. Deploy:
   - `echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook APP`
   - Or `kata restart APP` if the app dir already exists
4. Open https://APP.localhost/.

Notes

- The web service joins both the internal network and the `traefik-proxy` network so Traefik can reach it.
- The database only joins the internal network, so it is not reachable externally.
- Adjust credentials in the `environment` block as needed; this example uses defaults for simplicity.
