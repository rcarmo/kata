# Minimal Python example

A tiny FastAPI app deployed with Kata and Traefik.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block
- `app.py` — FastAPI app with a single endpoint
- `requirements.txt` — Python deps installed into `/venv` by the runtime hook

## How to try

1. Ensure Kata is set up on the host: `kata setup`
2. Copy this folder to your Kata apps directory (replace APP with your app name):
   - `cp -a docs/examples/minimal-python "$HOME/app/APP"`
3. Deploy using the internal hook (or push via git if you set that up):
   - `echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook APP`
   - Or simply run `kata restart APP` if the app dir already exists
4. Open https://app.localhost/ (change the host in the `traefik` block if needed).

Notes:

- If you’re using a real domain, set your host rule via Traefik labels or a `traefik:` block.
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
