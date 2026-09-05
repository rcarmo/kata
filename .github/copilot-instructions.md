# Working on Kata

Kata is deliberately a single-file Python 3.12+ application. Keep runtime code in
`kata.py`; add focused helpers rather than modules or a framework. Tests live in
`tests/test_kata.py` and use standard-library `unittest` and mocks.

## Verification

Install `click` and `pyyaml` in a virtual environment, then run:

```bash
python -m unittest discover -s tests
python kata.py --help
git diff --check
```

`make test` runs the same unittest discovery. There is no configured typecheck or
lint target. Help output alone is not a behavioural test. Do not initialise Swarm,
remove containers, or change a shared Docker host to run tests without permission.

## Code conventions

Use explicit imports, `snake_case` functions and `UPPER_SNAKE_CASE` constants.
Keep changes small and add regression tests for failure paths. Use argv lists,
not shell interpolation, for external commands. Preserve binary secret data and
never include secret values in exceptions or progress output.

Lifecycle helpers use boolean results where documented. Callers must check them.
Use `checked_call` for CLI subprocess operations whose failure must reach SSH/Make,
`error` for diagnostics and `fatal` for a terminal failure. Do not report success
after failed cleanup or ignore teardown failures before starting another deployment.

## Documentation

The implementation generates `.docker-compose.yaml` from `kata-compose.yaml`.
Routing labels use an opt-in `traefik:` block; Caddy is not supported. Shared
Traefik bootstrap currently runs even without a routing block. Compose and Swarm
are both required project targets; do not remove either to simplify changes.

Keep the README, `docs/INSTALL.md`, `docs/MANUAL.md`, `docs/SPEC.md` and affected
example READMEs consistent with the code. Document limitations rather than
presenting intended behaviour as implemented. In particular, restart is not an
initial deploy, container resolution is local-node only, and mocked tests do not
establish live Swarm compatibility. The spec records verification limits.
