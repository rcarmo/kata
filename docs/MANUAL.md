# Operating Kata

![Kata logo](kata-256.png)

Kata keeps its implementation in one Python file. Git pushes prepare runtime dependencies and generate `.docker-compose.yaml`; lifecycle commands operate on that generated deployment. Install it using the [installation guide](INSTALL.md), and use [SPEC.md](SPEC.md) for configuration details and known limitations.

## Deploying and restarting

Push a repository containing `kata-compose.yaml` to `kata@host:APP`. App names start with a letter or digit and otherwise contain letters, digits, `_` or `-`. Invalid names are rejected, not rewritten.

Post-receive hooks serialize deployments with `repos/APP/kata-deploy.lock`. Failed clone, fetch, reset or submodule commands stop deployment. Deleted refs are skipped. Other ref updates are deployed without a branch allowlist; push only the intended deployment branch. The lock does not cover concurrent manual lifecycle commands.

```bash
kata restart APP
kata restart APP web
kata restart APP builder --logs
kata stop APP
```

Whole-app restart stops then starts the existing generated configuration. It does not regenerate YAML or install changed dependencies; push a commit for that. Swarm restarts wait up to 60 seconds for teardown and abort on timeout or query failure. Per-service Swarm restart uses `docker service update --force`, avoiding full stack teardown; Compose uses `restart` for the selected services.

For the forced SSH key installed by Kata, the Makefile recipe is:

```makefile
deploy: deploy-production
	ssh -t kata@$(PRODUCTION_SERVER) restart $(APP_NAME) builder --logs
```

A regular SSH shell account needs `kata` before `restart`. `--logs` follows the last named service after a successful restart using `--tail 0`; output emitted before log following starts may be missed. Use a separate `logs --tail 100` call when early builder output matters.

## Finding services and running commands

```bash
kata services APP
kata containers APP web
kata ps APP
kata ps APP web
kata run APP web sh
kata run --index 1 APP web sh
kata logs APP web --tail 100 -f
```

`containers` and `run` resolve running containers on the local Docker daemon using labels. They do not connect to other Swarm nodes. `--index` is a zero-based index in the returned Docker list, not a stable Swarm replica slot. Use `ps` to see remote task placement. No match is an error for `run`; raw names require explicit `kata docker exec`.

`run` allocates a TTY only when stdin and stdout are terminals. Use `--` to separate Kata options from commands with their own options, for example `kata run -- APP web sh -c 'echo hello'` locally. The forced SSH command's argument splitting is not a general shell quoting protocol; use simple arguments or an application script over that path.

Swarm logs require a service name; Compose logs may cover the entire app. Swarm app-wide `ps` uses `docker stack ps`. `ls` retains a legacy name-prefix running marker and is not reliable for Swarm; prefer `services` and `ps`.

## Configuration and modes

```bash
kata config:stack APP
kata config:docker APP
kata config:traefik APP --json
kata traefik:ls APP
kata traefik:inspect APP
kata mode APP
kata mode APP compose
```

`config:stack` displays the source YAML. `config:docker` displays generated YAML. Rendering Traefik configuration can invoke parsing and runtime preparation, so it is not guaranteed read-only.

Mode changes stop the old deployment before saving the new mode. Swarm teardown must finish before starting Compose. A failed new start retains the new mode for recovery, without automatic rollback. For a lasting choice across Git deployments, set `x-kata-mode` in the source YAML: deployment recalculates the mode and can overwrite a CLI-only choice.

Environment precedence is base paths/PUID/PGID, top-level environment, config `ENV`, config `.env`, then service environment. Both config files are loaded if present. See the spec for parser limitations; container processes should listen on `0.0.0.0` when another container must reach them.

## Routing

Routing labels are opt-in through a nonempty `traefik:` block:

```yaml
traefik:
  host: app.example.com
  service: web
  port: 8000
  entrypoints: [websecure]
  enable_http_redirect: true
```

The port defaults to 8000, not the first exposed port. TLS defaults on when `websecure` is selected. No redirect is generated unless requested. The selected service joins the proxy network unless it uses `network_mode`. Kata does not publish application ports automatically.

The shared Traefik bootstrap runs on deployment even when label generation is disabled. Existing proxy compatibility and multi-node Swarm routing need explicit checking; neither labels nor an ACME volume alone guarantees HTTPS. The `caddy:` key is rejected.

## Secrets, runtime images and updates

```bash
kata secrets:set TOKEN=@/path/to/token
kata secrets:set TOKEN=-
kata secrets:ls
kata secrets:rm TOKEN
kata runtime:rebuild python
kata runtime:rebuild-all
kata runtime:clean
kata update --no-restart
```

Secret file/stdin bytes are preserved. Names allow letters, digits, `.`, `_` and `-`, starting with a letter or digit. `NAME=value` treats an existing path as a file for compatibility; use `@file` to be explicit. Avoid literal secrets on the command line. Creation requires a Swarm manager and fails non-zero; legacy list/removal precondition warnings are not a universal exit-status contract.

Runtime images are reused until rebuilt or removed. Runtime preparation runs on deployment and failures abort it. Tags and apt packages are not frozen: reproducible builds need a maintained image/snapshot policy. The updater validates syntax, requires a backup, preserves mode bits and uses an atomic replacement; it trusts the upstream repository.

## Removing an app

```bash
kata rm APP
kata rm APP --wipe
```

Removal normally deletes code, runtime state, logs and the bare repository, while retaining data/config. `--wipe` includes data/config; `--force` skips confirmation. Kata rejects redirected per-app paths before teardown and waits for Swarm teardown before deleting directory contents in a root BusyBox container. Container or host deletion failures exit non-zero and do not report success. A failed removal can still be partial; keep backups.

Docker access is administrative access. These checks do not provide hostile multi-tenant isolation or protect against a concurrent privileged process changing paths. Do not run the development-only `tools/updater.py` HTTP upload server on an exposed host.

## Tests and troubleshooting

Activate a Python environment with `click` and `pyyaml`, then run `make test` or `python -m unittest discover -s tests`. Tests mock Docker unless stated otherwise; see the [verification notes](SPEC.md#verification-and-remaining-limits).

For deployment failures, inspect `ps`, service logs and the generated YAML before retrying. For TLS, check DNS, entrypoints and the proxy's own logs. For Swarm, local runtime images and bind-mounted app files must exist on whichever node receives the task; Kata does not distribute them.
