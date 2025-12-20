# Minimal Node.js example

A tiny Express app deployed with Kata using the `runtime: nodejs` shortcut.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block (HTTP-only in this example)
- `app.js` — Express app with a single endpoint
- `package.json` — npm manifest; dependencies are installed by the runtime hook

## How to try

1. Ensure Kata is set up on the host: `kata setup`
2. Copy this folder to your Kata apps directory (replace APP with your app name):
   - `cp -a docs/examples/minimal-nodejs "$HOME/app/APP"`
3. Deploy using the internal hook (or push via git if you set that up):
   - `echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook APP`
   - Or simply run `kata restart APP` if the app dir already exists
4. Open http://app.localhost/ (HTTP only; change the host in the `traefik` block if needed).

Notes:

- You do not need host port mappings; Traefik shares the `traefik-proxy` Docker network with the service.
- Edit the host rule via Traefik labels if you want a real domain instead of `<app>.localhost`.
