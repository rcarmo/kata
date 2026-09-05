# Installing Kata

![Kata logo](kata-256.png)

Use a dedicated deployment account on a trusted host. Access to the Docker daemon is administrative access; Kata's forced SSH command is not a tenant security boundary.

## Dependencies

Install Python 3.12 or newer, Git, OpenSSH, curl and Docker. Compose deployments need the `docker compose` plugin (the legacy `docker-compose` binary is a fallback). Swarm deployments need an active manager. Kata does not initialise Swarm for you.

The Python dependencies are `click` and `pyyaml`. Use a virtual environment rather than modifying a distribution-managed Python installation:

```bash
python3 -m venv "$HOME/.local/share/kata-venv"
"$HOME/.local/share/kata-venv/bin/pip" install click pyyaml
mkdir -p "$HOME/bin" "$HOME/.local/lib/kata"
curl -fL https://raw.githubusercontent.com/rcarmo/kata/main/kata.py \
  -o "$HOME/.local/lib/kata/kata.py"
chmod 755 "$HOME/.local/lib/kata/kata.py"
cat > "$HOME/bin/kata" <<'SH'
#!/bin/sh
exec "$HOME/.local/share/kata-venv/bin/python" "$HOME/.local/lib/kata/kata.py" "$@"
SH
chmod 755 "$HOME/bin/kata"
export PATH="$HOME/bin:$PATH"
kata setup
```

Persist the PATH setting in your shell configuration. `KATA_ROOT` defaults to `$HOME`, not `~/.kata`; `setup` creates `app`, `data`, `config`, `envs`, `logs` and `repos` there. Set `KATA_ROOT` before setup if you want a different root.

## SSH deployment

Install the client's public key on the deployment host:

```bash
kata setup:ssh /path/to/client-key.pub
```

The generated forced command invokes `kata.py` directly. Its shebang uses `python3` from the SSH session's PATH, not the wrapper above. Ensure that Python has `click` and `pyyaml` available in that non-interactive environment before using Git pushes. With the virtual environment above, an administrator can point the forced command at its absolute Python interpreter followed by the absolute script path. Keep the generated forwarding restrictions.

Use a dedicated key. For a forced-command key, commands are Kata arguments:

```bash
ssh kata@paas help
ssh kata@paas restart hello web
```

For a regular shell account, include the executable: `ssh user@host kata restart hello web`.

## First deployment

Clone this repository on your workstation, copy an example into a separate repository, and push it to the configured deployment account:

```bash
git clone https://github.com/rcarmo/kata.git
cp -R kata/docs/examples/minimal-python hello
cd hello
# Edit kata-compose.yaml: choose a real hostname and deployment mode.
git init -b main
git add .
git commit -m 'Initial app'
git remote add paas kata@paas:hello
git push paas main
```

The push creates the bare repository and generates `.docker-compose.yaml`. `restart` only operates on an already generated deployment; copying an example into `app/hello` and running `restart` is not an initial deployment procedure.

The examples' `.localhost` names are placeholders. They do not provision trusted certificates. For public HTTPS, configure a real hostname, DNS, ACME email and reachable ports 80/443. For local testing use `entrypoints: [web]`, `tls: false` and no redirect, or supply your own TLS configuration.

## Traefik and updates

Routing labels require a nonempty `traefik:` block with `host`. Deployment currently calls shared Traefik setup even without routing enabled, so it may create `traefik-proxy`, `traefik-acme` and `kata-traefik`. See the [specification](SPEC.md) before integrating an existing proxy or a multi-node Swarm.

```bash
kata update --no-restart
```

The updater follows HTTPS redirects, checks Python syntax, saves `.backup`, preserves permissions and replaces the script atomically. Without `--no-restart`, it re-executes the new script to display help. This trusts upstream source; syntax checking is not signature verification. Keep the script directory writable by the deployment account.

See the [manual](MANUAL.md) for operations and the [README](../README.md) for examples.
