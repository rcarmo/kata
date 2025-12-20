# Static site example

A static HTML site served by Kata’s `runtime: static` BusyBox httpd image.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block (HTTP-only in this example)
- `public/index.html` — sample static page

## How to try

1. Ensure Kata is set up on the host: `kata setup`
2. Copy this folder to your Kata apps directory (replace APP with your app name):
   - `cp -a docs/examples/static-site "$HOME/app/APP"`
3. Deploy using the internal hook (or push via git if you set that up):
   - `echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook APP`
   - Or simply run `kata restart APP` if the app dir already exists
4. Open http://site.localhost/ (or http://alias.localhost/ from the extra router labels; adjust the `traefik` block to change hosts).

Notes:

- `DOCROOT` can be adjusted in `kata-compose.yaml` if you prefer a different folder.
- To change hostnames, edit the `traefik.http.routers.site-alt.rule` label (it uses `Host(`site.localhost`) || Host(`alias.localhost`)` by default).
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
