# Minimal PHP example

A tiny PHP app served by the built-in PHP server using Kata’s `runtime: php` shortcut.

## Files

- `kata-compose.yaml` — stack definition; Traefik routing is configured via the `traefik` block (HTTP-only in this example)
- `public/index.php` — single endpoint returning JSON
- `composer.json` — present so the runtime hook can run `composer install`

## How to try

1. Ensure Kata is set up on the host: `kata setup`
2. Copy this folder to your Kata apps directory (replace APP with your app name):
   - `cp -a docs/examples/minimal-php "$HOME/app/APP"`
3. Deploy using the internal hook (or push via git if you set that up):
   - `echo "0000000000000000000000000000000000000000 $(git rev-parse HEAD) refs/heads/main" | kata git-hook APP`
   - Or simply run `kata restart APP` if the app dir already exists
4. Open http://app.localhost/ (HTTP only; change the host in the `traefik` block if needed).

Notes:

- The runtime hook runs `composer install --no-dev --optimize-autoloader`; you can add dependencies to `composer.json` as needed.
- No host port publishing is required; Traefik shares the `traefik-proxy` Docker network with the service.
