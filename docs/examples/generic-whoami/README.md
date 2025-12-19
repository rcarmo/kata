# Generic container example (no runtime)

A minimal example that uses an off-the-shelf image (`traefik/whoami`) without Kata runtime shortcuts.

## Files

- `kata-compose.yaml` — stack definition; Traefik labels are generated automatically

## How to try

1. Ensure Kata is set up on the host: `kata setup`
2. Copy this folder to your Kata apps directory (replace APP with your app name):
   - `cp -a docs/examples/generic-whoami "$HOME/app/APP"`
3. Deploy using the internal hook (or push via git if you set that up):
   - `echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook APP`
   - Or simply run `kata restart APP` if the app dir already exists
4. Open https://APP.localhost/.

Notes:

- This example demonstrates the `image:` path; no runtime image is built, and no volumes are mounted by default.
- Add your own labels/env/ports as needed for other off-the-shelf images.
