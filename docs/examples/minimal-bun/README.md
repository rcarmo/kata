# Minimal Bun example

A tiny JSON endpoint powered by Bun using Kata’s `runtime: bun` shortcut.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block
- `index.ts` — Bun server with a single route
- `package.json` — present so the runtime hook can run `bun install`

## How to try

1. Ensure Kata is set up on the host: `kata setup`
2. Copy this folder to your Kata apps directory (replace APP with your app name):
   - `cp -a docs/examples/minimal-bun "$HOME/app/APP"`
3. Deploy using the internal hook (or push via git if you set that up):
   - `echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook APP`
   - Or simply run `kata restart APP` if the app dir already exists
4. Open https://app.localhost/ (change the host in the `traefik` block if needed).

Notes:

- The runtime hook runs `bun install`; add any dependencies to `package.json`.
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
