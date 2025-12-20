#!/usr/bin/env python3

"Kata Micro-PaaS - Piku refactor"

try:
    from sys import version_info
    assert version_info >= (3, 12)
except AssertionError:
    exit("Kata requires Python 3.12 or above")

from http.client import HTTPSConnection
from json import dumps
from os import chmod, environ, getgid, getuid, listdir, makedirs, remove, stat
from os.path import abspath, dirname, exists, join, realpath
from re import sub
from shutil import copyfile, rmtree, which
from stat import S_IRUSR, S_IWUSR, S_IXUSR
from subprocess import STDOUT, call, check_output, run
from sys import argv, stderr, stdin, stdout
from tempfile import NamedTemporaryFile
from traceback import format_exc
from urllib.parse import urlparse

from click import UNPROCESSED, argument
from click import echo as click_echo
from click import group, option
from yaml import safe_dump, safe_load

# === Make sure we can access all system and user binaries ===

if 'sbin' not in environ['PATH']:
    environ['PATH'] = "/usr/local/sbin:/usr/sbin:/sbin:" + environ['PATH']
if '.local' not in environ['PATH']:
    environ['PATH'] = environ['HOME'] + "/.local/bin:" + environ['PATH']

# === Globals - all tweakable settings are here ===

KATA_RAW_SOURCE_URL = "https://github.com/rcarmo/kata/raw/refs/heads/main/kata.py"
KATA_ROOT = environ.get('KATA_ROOT', join(environ['HOME']))
KATA_BIN = join(environ['HOME'], 'bin')
KATA_SCRIPT = realpath(__file__)
APP_ROOT = abspath(join(KATA_ROOT, "app"))
DATA_ROOT = abspath(join(KATA_ROOT, "data"))
CONFIG_ROOT = abspath(join(KATA_ROOT, "config"))
GIT_ROOT = abspath(join(KATA_ROOT, "repos"))
LOG_ROOT = abspath(join(KATA_ROOT, "logs"))
ENV_ROOT = abspath(join(KATA_ROOT, "envs"))
PUID = getuid()
PGID = getgid()
DOCKER_COMPOSE = ".docker-compose.yaml"
KATA_COMPOSE = "kata-compose.yaml"
KATA_MODE_FILE = ".kata-mode"  # stores 'swarm' or 'compose' per app
TRAEFIK_IMAGE = "traefik:v3.6.5"
ROOT_FOLDERS = ['APP_ROOT', 'DATA_ROOT', 'ENV_ROOT', 'CONFIG_ROOT', 'GIT_ROOT', 'LOG_ROOT']
if KATA_BIN not in environ['PATH']:
    environ['PATH'] = KATA_BIN + ":" + environ['PATH']

# === Make sure we can access kata user-installed binaries === #

PYTHON_DOCKERFILE = """
FROM debian:trixie-slim
ARG DEBIAN_FRONTEND=noninteractive
RUN apt update \
 && apt dist-upgrade -y \
 && apt-get -qq install \
    git \
    openssh-client \
    python3-pip \
    python3-dev \
    python3-venv
ENV VIRTUAL_ENV=/venv
ENV PATH=/venv/bin:$PATH
VOLUME ["/app", "/config", "/data", "/venv"]
WORKDIR /app
CMD ["python3", "-m", "app"]
"""

NODEJS_DOCKERFILE = """
FROM debian:trixie-slim
ARG DEBIAN_FRONTEND=noninteractive
RUN apt update \
 && apt dist-upgrade -y \
 && apt-get -qq install \
    git \
    openssh-client \
    nodejs \
    npm \
    yarnpkg
ENV NODE_PATH=/venv
ENV NPM_CONFIG_PREFIX=/venv
ENV PATH=/venv/bin:/venv/.bin:$PATH
VOLUME ["/app", "/config", "/data", "/venv"]
WORKDIR /app
CMD ["node", "app.js"]
"""

PHP_DOCKERFILE = """
FROM debian:trixie-slim
ARG DEBIAN_FRONTEND=noninteractive
RUN apt update \
 && apt dist-upgrade -y \
 && apt-get -qq install \
    git \
    openssh-client \
    php-cli \
    php-curl \
    php-mbstring \
    php-xml \
    php-zip \
    composer
VOLUME ["/app", "/config", "/data", "/venv"]
WORKDIR /app
CMD ["php", "-S", "0.0.0.0:8000", "-t", "/app"]
"""

BUN_DOCKERFILE = """
FROM oven/bun:1-alpine
RUN apk add --no-cache \
    git \
    openssh-client
ENV NODE_PATH=/venv
ENV BUN_INSTALL=/venv
ENV PATH=/venv/bin:$PATH
VOLUME ["/app", "/config", "/data", "/venv"]
WORKDIR /app
CMD ["bun", "run", "index.js"]
"""

STATIC_DOCKERFILE = """
FROM busybox:stable-musl
ENV PORT=8000
ENV DOCROOT=/app
EXPOSE 8000
VOLUME ["/app"]
WORKDIR /app
CMD ["sh", "-c", "httpd -f -p ${PORT} -h ${DOCROOT}"]
"""

RUNTIME_IMAGES = {
    'kata/python': PYTHON_DOCKERFILE,
    'kata/nodejs': NODEJS_DOCKERFILE,
    'kata/php': PHP_DOCKERFILE,
    'kata/bun': BUN_DOCKERFILE,
    'kata/static': STATIC_DOCKERFILE
}


def traefik_is_running() -> bool:
    """Return True if a Traefik container or service appears to be running."""
    # Check regular containers (compose or standalone) first
    try:
        containers = check_output(['docker', 'ps', '--format', '{{.Names}} {{.Image}}'], universal_newlines=True)
        for line in containers.splitlines():
            parts = line.lower().split()
            if not parts:
                continue
            image = parts[1] if len(parts) > 1 else ''
            if 'traefik' in image:
                return True
    except Exception:
        pass

    # Check swarm services if this node is a manager
    if docker_is_swarm_manager():
        try:
            services = check_output(['docker', 'service', 'ls', '--format', '{{.Name}} {{.Image}}'], universal_newlines=True, stderr=STDOUT)
            for line in services.splitlines():
                parts = line.lower().split()
                if not parts:
                    continue
                image = parts[1] if len(parts) > 1 else ''
                if 'traefik' in image:
                    return True
        except Exception:
            pass

    return False


def ensure_docker_network(network_name: str) -> bool:
    """Ensure a Docker network exists without erroring if it already exists."""
    try:
        check_output(['docker', 'network', 'inspect', network_name], stderr=STDOUT, universal_newlines=True)
        return True
    except Exception:
        pass
    try:
        check_output(['docker', 'network', 'create', network_name], stderr=STDOUT, universal_newlines=True)
        return True
    except Exception as exc:
        echo(f"Warning: could not ensure network '{network_name}': {exc}", fg='yellow')
        return False


def ensure_docker_volume(volume_name: str) -> bool:
    """Ensure a Docker volume exists without erroring if it already exists."""
    try:
        check_output(['docker', 'volume', 'inspect', volume_name], stderr=STDOUT, universal_newlines=True)
        return True
    except Exception:
        pass
    try:
        check_output(['docker', 'volume', 'create', volume_name], stderr=STDOUT, universal_newlines=True)
        return True
    except Exception as exc:
        echo(f"Warning: could not ensure volume '{volume_name}': {exc}", fg='yellow')
        return False


def ensure_shared_traefik() -> None:
    """Ensure a single shared Traefik is running on this host.

    Creates the external network/volume if missing, tries to start an existing
    container named 'kata-traefik' if present, and launches a fresh instance if
    nothing is running. This keeps one ACME store and one set of entrypoints
    for all stacks.
    """

    network_name = 'traefik-proxy'
    volume_name = 'traefik-acme'
    acme_email = environ.get('KATA_ACME_EMAIL', 'admin@example.com')

    # Ensure shared network/volume exist without noisy errors if already present
    if not ensure_docker_network(network_name):
        return
    if not ensure_docker_volume(volume_name):
        return

    # If any traefik is running, reuse it
    if traefik_is_running():
        return

    # Attempt to start a stopped shared container if it exists
    try:
        status = check_output(['docker', 'inspect', '-f', '{{.State.Status}}', 'kata-traefik'], stderr=STDOUT, universal_newlines=True).strip().lower()
        if status != 'running':
            call(['docker', 'start', 'kata-traefik'], stdout=stdout, stderr=stderr, universal_newlines=True)
            if traefik_is_running():
                return
        else:
            return
    except Exception:
        pass

    run_shared_traefik(enable_dashboard=False)


def run_shared_traefik(enable_dashboard: bool = False,
                       dashboard_bind: str = '127.0.0.1',
                       dashboard_port: int = 8080,
                       web_bind: str = '80:80',
                       websecure_bind: str = '443:443'):
    """(Re)start the shared Traefik container with optional dashboard exposure and custom binds."""
    network_name = 'traefik-proxy'
    volume_name = 'traefik-acme'
    acme_email = environ.get('KATA_ACME_EMAIL', 'admin@example.com')

    # Build port mappings
    ports = []
    if web_bind:
        ports.append(web_bind)
    if websecure_bind:
        ports.append(websecure_bind)
    entrypoints = [
        '--providers.docker=true',
        '--providers.docker.exposedbydefault=false',
        '--entrypoints.web.address=:80',
        '--entrypoints.websecure.address=:443',
        f'--certificatesresolvers.default.acme.email={acme_email}',
        '--certificatesresolvers.default.acme.storage=/etc/traefik/acme.json',
        '--certificatesresolvers.default.acme.httpchallenge.entrypoint=web'
    ]

    if enable_dashboard:
        bind_addr = dashboard_bind or '127.0.0.1'
        ports.append(f"{bind_addr}:{dashboard_port}:8080")
        entrypoints.extend([
            '--entrypoints.traefik.address=:8080',
            '--api.dashboard=true',
            '--api.insecure=true'
        ])

    echo("-----> Starting shared Traefik router 'kata-traefik'", fg='yellow')
    cmd = [
        'docker', 'run', '-d', '--name', 'kata-traefik', '--restart', 'unless-stopped',
        '--network', network_name
    ]
    for p in ports:
        cmd += ['-p', p]
    cmd += [
        '-v', '/var/run/docker.sock:/var/run/docker.sock:ro',
        '-v', f'{volume_name}:/etc/traefik',
        TRAEFIK_IMAGE
    ]
    cmd.extend(entrypoints)
    call(cmd, stdout=stdout, stderr=stderr, universal_newlines=True)



def apply_traefik(app_name, compose_def, traefik_cfg):
    """Inject traefik service + labels based on a simplified traefik config block.

    traefik_cfg expected keys:
      host: required hostname
      port: upstream service port (int/str)
      service: target service name (defaults to first service)
      entrypoints: list[str] (default ["websecure"])
      enable_http_redirect: bool (default False)
      acme_email: str (default "admin@example.com")
      certresolver: str (default "default")
    """
    if not traefik_cfg or not isinstance(traefik_cfg, dict):
        return

    services = compose_def.get('services', {})
    if not services:
        echo("Warning: no services defined; skipping traefik label generation", fg='yellow')
        return

    host = str(traefik_cfg.get('host', '')).strip()
    if not host:
        echo("Warning: 'traefik.host' missing; skipping traefik labels", fg='yellow')
        return

    # Support comma-separated hostnames; build an OR rule for compatibility
    hostnames = [h.strip() for h in host.split(',') if h and h.strip()]
    if not hostnames:
        hostnames = [host]
    if len(hostnames) == 1:
        host_rule = f"Host(`{hostnames[0]}`)"
    else:
        host_rule = " || ".join([f"Host(`{h}`)" for h in hostnames])

    service_name = traefik_cfg.get('service')
    if not service_name:
        # pick first declared service
        service_name = next(iter(services.keys()))
    if service_name not in services:
        echo(f"Warning: traefik.service '{service_name}' not found; skipping traefik labels", fg='yellow')
        return

    port = traefik_cfg.get('port', None)
    if port is None:
        echo("Warning: 'traefik.port' missing; defaulting to 8000", fg='yellow')
        port = 8000

    entrypoints = traefik_cfg.get('entrypoints', ['websecure'])
    if isinstance(entrypoints, str):
        entrypoints = [entrypoints]
    entrypoints = [str(e) for e in entrypoints if e]
    if not entrypoints:
        entrypoints = ['websecure']

    certresolver = traefik_cfg.get('certresolver', 'default')
    enable_redirect = bool(traefik_cfg.get('enable_http_redirect', False))
    tls_enabled = traefik_cfg.get('tls')
    if tls_enabled is None:
        tls_enabled = 'websecure' in entrypoints
    acme_email = traefik_cfg.get('acme_email', 'admin@example.com')
    inject_service = bool(traefik_cfg.get('inject_service', True))
    acme_volume_external = bool(traefik_cfg.get('acme_volume_external', True))

    target_service = services[service_name]

    # Host network_mode services cannot be attached to traefik-proxy; skip labels.
    if isinstance(target_service, dict) and target_service.get('network_mode'):
        echo(f"Warning: service '{service_name}' uses network_mode; skipping Traefik labels and network attachment.", fg='yellow')
        return

    # Shared traefik network/volume (external) so one Traefik can front multiple stacks
    network_name = traefik_cfg.get('network', 'traefik-proxy')
    volume_name = traefik_cfg.get('acme_volume', 'traefik-acme')

    # Normalize labels container form (dict) for compose; stack deploy will map deploy.labels separately if needed.
    labels = target_service.get('labels')
    if labels is None:
        labels = {}
    elif isinstance(labels, list):
        # convert list ['k=v'] into dict
        converted = {}
        for item in labels:
            if '=' in item:
                k, v = item.split('=', 1)
                converted[k] = v
        labels = converted
    elif not isinstance(labels, dict):
        labels = {}

    router_name = app_name
    service_key = app_name

    labels[f"traefik.enable"] = "true"
    labels[f"traefik.http.routers.{router_name}.rule"] = host_rule
    labels[f"traefik.http.routers.{router_name}.entrypoints"] = ",".join(entrypoints)
    labels[f"traefik.http.routers.{router_name}.service"] = service_key
    labels[f"traefik.http.services.{service_key}.loadbalancer.server.port"] = str(port)
    if tls_enabled:
        labels[f"traefik.http.routers.{router_name}.tls"] = "true"
        labels[f"traefik.http.routers.{router_name}.tls.certresolver"] = certresolver

    if enable_redirect:
        # add middleware to redirect web -> websecure
        labels[f"traefik.http.routers.{router_name}.entrypoints"] = "websecure"
        labels[f"traefik.http.middlewares.{router_name}-redirect.redirectscheme.scheme"] = "https"
        labels[f"traefik.http.middlewares.{router_name}-redirect.redirectscheme.permanent"] = "true"
        labels[f"traefik.http.routers.{router_name}.middlewares"] = f"{router_name}-redirect"

    target_service['labels'] = labels
    deploy = target_service.get('deploy', {}) if isinstance(target_service.get('deploy'), dict) else {}
    deploy_labels = deploy.get('labels')
    if deploy_labels is None:
        deploy_labels = {}
    elif isinstance(deploy_labels, list):
        converted = {}
        for item in deploy_labels:
            if '=' in item:
                k, v = item.split('=', 1)
                converted[k] = v
        deploy_labels = converted
    elif not isinstance(deploy_labels, dict):
        deploy_labels = {}
    # mirror labels into deploy.labels for swarm compatibility
    for k, v in labels.items():
        deploy_labels[k] = v
    deploy['labels'] = deploy_labels
    target_service['deploy'] = deploy

    # Attach to shared network
    svc_networks = target_service.get('networks')
    if svc_networks is None:
        svc_networks = []
    if isinstance(svc_networks, str):
        svc_networks = [svc_networks]
    if network_name not in svc_networks:
        svc_networks.append(network_name)
    target_service['networks'] = svc_networks

    # Declare shared network as external
    networks = compose_def.get('networks', {})
    if 'networks' not in compose_def:
        compose_def['networks'] = networks
    networks.setdefault(network_name, {'external': True})

    # Declare shared ACME volume as external
    volumes = compose_def.get('volumes', {})
    if 'volumes' not in compose_def:
        compose_def['volumes'] = volumes

    # Declare ACME volume (external by default so a single Traefik can own it)
    volumes.setdefault(volume_name, {'external': acme_volume_external})

    # Optionally inject a Traefik service (singleton per host via runtime detection)
    if inject_service:
        if traefik_is_running():
            echo("-----> Detected running Traefik; reusing external network/volume", fg='yellow')
        else:
            if 'traefik' in services:
                echo("Warning: traefik service already present in compose; skipping auto-injection", fg='yellow')
            else:
                services['traefik'] = {
                    'image': TRAEFIK_IMAGE,
                    'command': [
                        '--providers.docker=true',
                        '--providers.docker.exposedbydefault=false',
                        '--entrypoints.web.address=:80',
                        '--entrypoints.websecure.address=:443',
                        '--certificatesresolvers.default.acme.email=' + acme_email,
                        '--certificatesresolvers.default.acme.storage=/etc/traefik/acme.json',
                        '--certificatesresolvers.default.acme.httpchallenge.entrypoint=web'
                    ],
                    'ports': ['80:80', '443:443'],
                    'volumes': [
                        '/var/run/docker.sock:/var/run/docker.sock:ro',
                        f'{volume_name}:/etc/traefik'
                    ],
                    'networks': [network_name],
                    'restart': 'unless-stopped'
                }

# === Utility functions ===

def echo(message, fg=None, nl=True, err=False) -> None:
    """Print a message with optional color"""
    click_echo(message, color=True if fg else None, nl=nl, err=err)


def base_env(app, env=None) -> dict:
    """Get the environment variables for an app"""
    base = {'PGID': str(PGID), 'PUID': str(PUID)}
    for key in ROOT_FOLDERS:
        try:
            path_value = globals()[key]
            base[key] = join(path_value, app)
        except KeyError:
            echo(f"Error: {key} not found in global variables", fg='red')
            exit(1)
    # If env is provided, update the base environment with it
    if env is not None:
        base.update(env)

    # finally, an ENV or .env file in the config directory overrides things
    # TODO: validate if this still makes sense
    for name in ['ENV', '.env']:
        env_file = join(CONFIG_ROOT, app, name)
        if exists(env_file):
            with open(env_file, 'r', encoding='utf-8') as f:
                base.update(dict(line.strip().split('=', 1) for line in f if '=' in line))
    return base


def expandvars(buffer, env, default=None, skip_escaped=False):
    """expand shell-style environment variables in a buffer"""
    def replace_var(match):
        return env.get(match.group(2) or match.group(1), match.group(0) if default is None else default)
    pattern = (r'(?<!\\)' if skip_escaped else '') + r'\$(\w+|\{([^}]*)\})'
    return sub(pattern, replace_var, buffer)


def expand_in_obj(obj, env: dict):
    """Recursively expand ${VAR} placeholders inside strings of nested structures."""
    if isinstance(obj, dict):
        return {k: expand_in_obj(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_in_obj(v, env) for v in obj]
    if isinstance(obj, str):
        return expandvars(obj, env)
    return obj


def load_yaml(filename, env=None):
    if not exists(filename):
        echo(f"File not found: {filename}", fg='red')
        return None
    if env is None:
        env = environ.copy()
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    content = expandvars(content, env)
    try:
        return safe_load(content)
    except Exception as e:
        echo(f"Error parsing YAML: {str(e)}", fg='red')
        return None

# === SSH and git Helpers ===

def setup_authorized_keys(ssh_fingerprint, script_path, pubkey):
    """Sets up an authorized_keys file to redirect SSH commands"""
    authorized_keys = join(environ['HOME'], '.ssh', 'authorized_keys')
    if not exists(dirname(authorized_keys)):
        makedirs(dirname(authorized_keys))
    # Restrict features and force all SSH commands to go through our script
    with open(authorized_keys, 'a', encoding='utf-8') as h:
        h.write(f"""command="FINGERPRINT={ssh_fingerprint:s} NAME=default {script_path:s} $SSH_ORIGINAL_COMMAND",no-agent-forwarding,no-user-rc,no-X11-forwarding,no-port-forwarding {pubkey:s}\n""")
    chmod(dirname(authorized_keys), S_IRUSR | S_IWUSR | S_IXUSR)
    chmod(authorized_keys, S_IRUSR | S_IWUSR)

# === Docker Helpers ===

def docker_check_image_exists(image_name):
    """Check if a Docker image exists locally"""
    output = check_output(['docker', 'image', 'list', '--format', '{{.Repository}}:{{.Tag}}'], stderr=STDOUT, universal_newlines=True)
    if image_name in output:
        return True
    return False


def docker_create_runtime_image(image_name, dockerfile_content):
    """Create a Docker image from a Dockerfile content"""
    try:
        with NamedTemporaryFile(delete=False, mode='w', suffix='.Dockerfile') as dockerfile:
            dockerfile.write(dockerfile_content)
            dockerfile_path = dockerfile.name
        output = check_output(['docker', 'build', '-t', image_name, '-f', dockerfile_path, '.'], stderr=STDOUT, universal_newlines=True)
        echo(f"Created '{image_name}' successfully.", fg='green')
        return True
    except Exception as e:
        echo(f"Error creating image: {str(e)}", fg='red')
        return False
    finally:
        remove(dockerfile_path)


def docker_remove_image(image_name: str, warn: bool = True) -> bool:
    """Remove a Docker image; return True on success, False on failure."""
    try:
        call(['docker', 'rmi', '-f', image_name], stdout=stdout, stderr=stderr, universal_newlines=True)
        return True
    except Exception as exc:
        if warn:
            echo(f"Warning: could not remove {image_name}: {exc}", fg='yellow')
        return False


def docker_rebuild_all_runtimes() -> bool:
    """Force rebuild of all built-in runtime images."""
    all_ok = True
    for image_name, dockerfile_content in RUNTIME_IMAGES.items():
        echo(f"-----> Rebuilding {image_name}", fg='yellow')
        docker_remove_image(image_name, warn=False)
        if not docker_create_runtime_image(image_name, dockerfile_content):
            all_ok = False
    return all_ok


def docker_rebuild_runtime(runtime: str) -> bool:
    """Force rebuild of a single built-in runtime image."""
    image_name = f"kata/{runtime}"
    dockerfile_content = RUNTIME_IMAGES.get(image_name)
    if not dockerfile_content:
        echo(f"Error: unknown runtime '{runtime}'. Valid: {', '.join([i.split('/',1)[1] for i in RUNTIME_IMAGES.keys()])}", fg='red')
        return False
    echo(f"-----> Rebuilding {image_name}", fg='yellow')
    docker_remove_image(image_name, warn=False)
    return docker_create_runtime_image(image_name, dockerfile_content)


def docker_remove_runtime_images() -> None:
    """Remove all built-in runtime images (kata/*)."""
    for image_name in RUNTIME_IMAGES.keys():
        echo(f"-----> Removing {image_name}", fg='yellow')
        docker_remove_image(image_name, warn=True)


def docker_handle_runtime_environment(app_name, runtime, destroy=False, env=None):
    image = f"kata/{runtime}"
    if not docker_check_image_exists(image) and not destroy:
        if not docker_create_runtime_image(image, RUNTIME_IMAGES[image]):
            exit(1)
    volumes = [
        "-v", f"{join(APP_ROOT, app_name)}:/app",
        "-v", f"{join(CONFIG_ROOT, app_name)}:/config",
        "-v", f"{join(DATA_ROOT, app_name)}:/data",
        "-v", f"{join(ENV_ROOT, app_name)}:/venv"
    ]
    if destroy:
        cmds = {
            'python': [['chown', '-hR', f'{PUID}:{PGID}', '/data'],
                       ['chown', '-hR', f'{PUID}:{PGID}', '/app'],
                       ['chown', '-hR', f'{PUID}:{PGID}', '/venv'],
                       ['chown', '-hR', f'{PUID}:{PGID}', '/config']],
            'nodejs': [['chown', '-hR', f'{PUID}:{PGID}', '/data'],
                       ['chown', '-hR', f'{PUID}:{PGID}', '/app'],
                       ['chown', '-hR', f'{PUID}:{PGID}', '/venv'],
                       ['chown', '-hR', f'{PUID}:{PGID}', '/config']],
            'php': [['chown', '-hR', f'{PUID}:{PGID}', '/data'],
                    ['chown', '-hR', f'{PUID}:{PGID}', '/app'],
                    ['chown', '-hR', f'{PUID}:{PGID}', '/venv'],
                    ['chown', '-hR', f'{PUID}:{PGID}', '/config']],
            'bun': [['chown', '-hR', f'{PUID}:{PGID}', '/data'],
                    ['chown', '-hR', f'{PUID}:{PGID}', '/app'],
                    ['chown', '-hR', f'{PUID}:{PGID}', '/venv'],
                    ['chown', '-hR', f'{PUID}:{PGID}', '/config']],
            'static': []
        }
    else:
        cmds = {
            'python': [['python3', '-m', 'venv', '/venv'],
                       ['pip3', 'install', '-r', '/app/requirements.txt']],
            'nodejs': [['npm', 'install']],
            'php': [['composer', 'install', '--no-dev', '--optimize-autoloader']],
            'bun': [['bun', 'install']],
            'static': []
        }
    for cmd in cmds.get(runtime, []):
        echo(f"Running: {' '.join(cmd)}", fg='green')
        call(['docker', 'run', '--rm'] + volumes + ['-i', f'kata/{runtime}'] + cmd,
             cwd=join(APP_ROOT, app_name), env=env, stdout=stdout, stderr=stderr, universal_newlines=True)

# === App Management ===

def exit_if_invalid(app, deployed=False):
    """Make sure the app exists"""
    app = sanitize_app_name(app)
    app_path = join(APP_ROOT, app)
    if not exists(app_path):
        echo(f"Error: app '{app}' not deployed!", fg='red')
        exit(1)
    return app


def sanitize_app_name(app) -> str:
    """Sanitize the app name"""
    if app:
        return sub(r'[^a-zA-Z0-9_-]', '', app)
    return app


def parse_compose(app_name, filename) -> tuple:
    """Parses the kata-compose.yaml"""

    # First pass: load with base env so top-level vars resolve
    env_base = base_env(app_name)
    data = load_yaml(filename, env_base)

    if not data:
        return None, None

    if data and 'caddy' in data:
        echo("Error: 'caddy:' is no longer supported. Use Traefik labels (implicit) instead.", fg='red')
        exit(1)

    env = {}
    if "environment" in data:
        env = {k: str(v) for k, v in data["environment"].items()}

    # Merge user env with base and re-expand placeholders across the loaded structure
    env = base_env(app_name, env)
    data = expand_in_obj(data, env)

    # Prepare env as a dict; we'll merge into services preserving service-defined values
    # echo(f"Using environment for {app_name}: {','.join([f'{k}={v}' for k, v in env.items()])}", fg='green')
    if not "services" in data:
        echo(f"Warning: no 'services' section found in {filename}", fg='yellow')
    services = data.get("services", {})

    for service_name, service in services.items():
        is_static = bool(service.pop('static', False)) if isinstance(service, dict) else False
        echo(f"-----> Preparing service '{service_name}'", fg='green')
        if is_static:
            service["image"] = "kata/static"
            service.setdefault("environment", {})
            # Let env normalization handle list/dict forms; defaults preserve existing
            if isinstance(service["environment"], dict):
                service["environment"].setdefault("PORT", "8000")
                service["environment"].setdefault("DOCROOT", "/app")

        if not "image" in service:
            if "runtime" in service:
                service["image"] = f"kata/{service['runtime']}"
                echo(f"=====> '{service_name}' will use runtime '{service['runtime']}'", fg='green')
                if service["image"] in RUNTIME_IMAGES:
                    docker_handle_runtime_environment(app_name, service["runtime"], env=env)
                else:
                    echo(f"Error: runtime '{service['runtime']}' not supported", fg='red')
                    exit(1)
                del service["runtime"]
            if not "volumes" in service:
                service["volumes"] = ["app:/app", "config:/config", "data:/data", "venv:/venv"]
            else:
                echo(f"Warning: service '{service_name}' has custom volumes, ensure they are correct", fg='yellow')
        if not "command" in service:
            if not is_static:
                echo(f"Warning: service '{service_name}' has no 'command' specified", fg='yellow')
                continue
        # No auto-expose: users must set ports/expose explicitly for reachable services.
        # Normalize and merge environment
        if "environment" not in service:
            service["environment"] = {}
        elif isinstance(service["environment"], list):
            # Convert list form ["K=V", "X=Y"] into a dict
            converted = {}
            for item in service["environment"]:
                if isinstance(item, str):
                    if '=' in item:
                        k, v = item.split('=', 1)
                        converted[str(k)] = str(v)
                    else:
                        # No value provided; default to empty string
                        converted[str(item)] = ""
                elif isinstance(item, dict):
                    for k, v in item.items():
                        converted[str(k)] = str(v)
            service["environment"] = converted
        elif not isinstance(service["environment"], dict):
            # Fallback to dict
            service["environment"] = {}
        # Merge base env without overriding service-defined values
        for k, v in env.items():
            if k not in service["environment"]:
                service["environment"][k] = str(v)

    traefik_config = {}
    if "traefik" in data.keys():
        traefik_config = data.get("traefik", {}) or {}
        del data["traefik"]

    # If the selected traefik target service uses network_mode, skip injection
    if traefik_config:
        target = traefik_config.get('service') or (next(iter(services.keys())) if services else None)
        if target and isinstance(services.get(target), dict) and services[target].get('network_mode'):
            echo(f"Warning: service '{target}' uses network_mode; skipping Traefik label injection.", fg='yellow')
            traefik_config = {}

    if not "volumes" in data.keys():
        volumes = {
            "app": join(APP_ROOT, app_name),
            "config": join(CONFIG_ROOT, app_name),
            "data": join(DATA_ROOT, app_name),
            "venv": join(ENV_ROOT, app_name)
        }
        for volume in ["app", "config", "data", "venv"]:
            makedirs(volumes[volume], exist_ok=True)
            data["volumes"] = data.get("volumes", {})
            data["volumes"][volume] = {
                "driver": "local",
                "driver_opts": {
                    "o": "bind",
                    "type": "none",
                    "device": volumes[volume]
                }
            }
    else:
        echo(f"Warning: using app-specific volume setup.", fg='yellow')
    
    if "environment" in data:
        del data['environment']

    # Apply Traefik labels and inject Traefik service if configured
    apply_traefik(app_name, data, traefik_config)
    return (data, traefik_config)

# === Orchestrator helpers ===

def docker_supports_swarm() -> bool:
    try:
        # docker info exits 0 even if not in swarm; we'll check Swarm: inactive in output
        out = check_output(['docker', 'info', '--format', '{{.Swarm.LocalNodeState}}'], universal_newlines=True).strip()
        return out.lower() == 'active'
    except Exception:
        return False


def docker_is_swarm_manager() -> bool:
    """Return True if this node is an active swarm manager (control available)."""
    try:
        info = check_output(['docker', 'info', '--format', '{{.Swarm.LocalNodeState}} {{.Swarm.ControlAvailable}}'], universal_newlines=True).strip().lower()
        parts = info.split()
        if len(parts) >= 2:
            state, control = parts[0], parts[1]
            return state == 'active' and control == 'true'
    except Exception:
        pass
    return False

def get_app_mode(app: str) -> str:
    """Returns 'swarm' or 'compose' for this app. Default: 'compose' if swarm inactive, else 'swarm'.
       Allows override via x-kata-mode in kata-compose.yaml or .kata-mode file saved on deploy."""
    app_path = join(APP_ROOT, app)
    # persisted override file
    mf = join(app_path, KATA_MODE_FILE)
    if exists(mf):
        try:
            return open(mf, 'r', encoding='utf-8').read().strip()
        except Exception:
            pass
    # compose file override
    compose_path = join(app_path, KATA_COMPOSE)
    if exists(compose_path):
        try:
            cfg = safe_load(open(compose_path, 'r', encoding='utf-8'))
            mode = cfg.get('x-kata-mode')
            if mode in ('swarm', 'compose'):
                return mode
        except Exception:
            pass
    # default based on swarm manager availability
    return 'swarm' if docker_is_swarm_manager() else 'compose'

def set_app_mode(app: str, mode: str):
    app_path = join(APP_ROOT, app)
    try:
        with open(join(app_path, KATA_MODE_FILE), 'w', encoding='utf-8') as f:
            f.write(mode)
    except Exception:
        pass

def get_compose_cmd() -> list:
    """Return the base compose command: ['docker','compose'] if available, else ['docker-compose']."""
    # Prefer docker compose (V2)
    try:
        out = check_output(['docker', 'compose', 'version'], stderr=STDOUT, universal_newlines=True)
        if out:
            return ['docker', 'compose']
    except Exception:
        pass
    # Fallback to docker-compose (V1)
    if which('docker-compose'):
        return ['docker-compose']
    # Last resort: assume docker compose exists
    return ['docker', 'compose']

def require_swarm_or_warn() -> bool:
    """Ensure Docker Swarm is active; print a helpful error if not."""
    if not docker_is_swarm_manager():
        echo("Error: Docker Swarm manager not available on this node. This command requires a Swarm manager.", fg='red')
        echo("Tip: Initialize Swarm with 'docker swarm init' or switch app mode to 'compose' where applicable.", fg='yellow')
        return False
    return True

# Basic deployment functions

def do_deploy(app, deltas={}, newrev=None):
    """Deploy an app by resetting the work directory"""

    app_path = join(APP_ROOT, app)
    compose_file = join(app_path, KATA_COMPOSE)

    env = {'GIT_WORK_DIR': app_path}
    if exists(app_path):
        echo(f"-----> Deploying app '{app}'", fg='green')
        call('git fetch --quiet', cwd=app_path, env=env, shell=True)
        if newrev:
            call(f'git reset --hard {newrev}', cwd=app_path, env=env, shell=True)
        call('git submodule init', cwd=app_path, env=env, shell=True)
        call('git submodule update', cwd=app_path, env=env, shell=True)
        ensure_shared_traefik()
        compose, traefik = parse_compose(app, compose_file)
        if not compose:
            echo(f"Error: could not parse {compose_file}", fg='red')
            return
        with open(join(APP_ROOT, app, DOCKER_COMPOSE), "w", encoding='utf-8') as f:
            f.write(safe_dump(compose))
        # Record chosen mode for subsequent lifecycle ops
        mode = 'swarm' if docker_supports_swarm() else 'compose'
        cfg_override = safe_load(open(compose_file, 'r', encoding='utf-8')) if exists(compose_file) else {}
        if isinstance(cfg_override, dict) and cfg_override.get('x-kata-mode') in ('swarm', 'compose'):
            mode = cfg_override['x-kata-mode']
        set_app_mode(app, mode)
        do_start(app)
    else:
        echo(f"Error: app '{app}' not found.", fg='red')


def do_start(app):
    app_path = join(APP_ROOT, app)
    if exists(join(app_path, DOCKER_COMPOSE)):
        mode = get_app_mode(app)
        echo(f"-----> Starting app '{app}' (mode: {mode})", fg='yellow')
        compose_path = join(app_path, DOCKER_COMPOSE)
        if mode == 'swarm':
            if not docker_is_swarm_manager():
                echo("Error: Docker Swarm manager not available on this node; cannot deploy stack.", fg='red')
                echo("Tip: run 'docker swarm init' on a manager or switch this app to compose mode (kata mode <app> compose).", fg='yellow')
                return
            call(['docker', 'stack', 'deploy', app, f'--compose-file={compose_path}', '--detach=true', '--resolve-image=never', '--prune'],
                 cwd=app_path, stdout=stdout, stderr=stderr, universal_newlines=True)
        else:
            # docker compose up -d
            call(get_compose_cmd() + ['-f', compose_path, 'up', '-d', '--remove-orphans'],
                 cwd=app_path, stdout=stdout, stderr=stderr, universal_newlines=True)


def do_stop(app):
    app_path = join(APP_ROOT, app)
    if exists(join(app_path, DOCKER_COMPOSE)):
        mode = get_app_mode(app)
        echo(f"-----> Stopping app '{app}' (mode: {mode})", fg='yellow')
        compose_path = join(app_path, DOCKER_COMPOSE)
        if mode == 'swarm':
            call(['docker', 'stack', 'rm', app],
                 cwd=app_path, stdout=stdout, stderr=stderr, universal_newlines=True)
        else:
            call(get_compose_cmd() + ['-f', compose_path, 'down', '--remove-orphans'],
                 cwd=app_path, stdout=stdout, stderr=stderr, universal_newlines=True)


def do_remove(app):
    app_path = join(APP_ROOT, app)
    if exists(join(app_path, DOCKER_COMPOSE)):
        yaml = safe_load(open(join(app_path, KATA_COMPOSE), 'r', encoding='utf-8').read())
        if 'services' in yaml:
            for service_name, service in yaml['services'].items():
                echo("---> Removing service: " + service_name, fg='yellow')
                if 'runtime' in service:
                    runtime = service['runtime']
                    docker_handle_runtime_environment(app, runtime, destroy=True)
        mode = get_app_mode(app)
        echo(f"-----> Removing '{app}' (mode: {mode})", fg='yellow')
        compose_path = join(app_path, DOCKER_COMPOSE)
        if mode == 'swarm':
            call(['docker', 'stack', 'rm', app],
                 cwd=app_path, stdout=stdout, stderr=stderr, universal_newlines=True)
        else:
            call(get_compose_cmd() + ['-f', compose_path, 'down', '--volumes', '--remove-orphans'],
                 cwd=app_path, stdout=stdout, stderr=stderr, universal_newlines=True)


def do_restart(app):
    """Restarts a deployed app"""
    do_stop(app)
    do_start(app)
    pass

# === CLI Commands ===

@group(context_settings=dict(help_option_names=['-h', '--help']))
def cli():
    """Kata: The other smallest PaaS you've ever seen"""
    pass

command = cli.command

@command('ls')
def cmd_apps():
    """List apps/stacks"""
    apps = listdir(APP_ROOT)
    if not apps:
        return

    containers = check_output(['docker', 'ps', '--format', '{{.Names}}'], universal_newlines=True).splitlines()
    for a in apps:
        running = False
        for c in containers:
            if c.startswith(a + '-'):
                running = True
                break
        echo(('*' if running else ' ') + a, fg='green')


@command('config:stack')
@argument('app')
def cmd_config(app):
    """Show configuration for an app"""
    app = exit_if_invalid(app)

    config_file = join(APP_ROOT, app, KATA_COMPOSE)
    if exists(config_file):
        echo(open(config_file).read().strip(), fg='white')
    else:
        echo(f"Warning: app '{app}' not deployed, no config found.", fg='yellow')


@command('secrets:set')
@argument('secrets', nargs=-1, required=True)
def cmd_secrets_set(secrets):
    """Set a docker secret: name=value, name=@filename, name=- (stdin), or just name (prompt)"""
    if not require_swarm_or_warn():
        return
    if not secrets:
        k = input("Secret name: ")
        echo("Enter secret value (end with EOF / Ctrl-D):", fg='yellow')
        v = stdin.read().strip()
        secrets = [f"{k}={v}"]
    
    for s in secrets:
        try:
            if '=' in s:
                k, v = s.split('=', 1)
                
                # Handle different value sources
                if v == '-':
                    # Read from stdin
                    echo(f"Reading secret '{k}' from stdin (end with EOF / Ctrl-D):", fg='yellow')
                    content = stdin.read()
                elif v.startswith('@'):
                    # Read from file
                    filename = v[1:]  # Remove the @ prefix
                    if not exists(filename):
                        echo(f"Error: File '{filename}' not found", fg='red')
                        continue
                    try:
                        # Try to read as text first, fall back to binary if needed
                        try:
                            with open(filename, 'r', encoding='utf-8') as f:
                                content = f.read()
                        except UnicodeDecodeError:
                            # File contains binary data, read as bytes and decode
                            with open(filename, 'rb') as f:
                                content = f.read().decode('utf-8', errors='replace')
                        echo(f"Reading secret '{k}' from file '{filename}'", fg='green')
                    except Exception as e:
                        echo(f"Error reading file '{filename}': {str(e)}", fg='red')
                        continue
                elif exists(v):
                    # If value looks like a file path and the file exists, read from it
                    try:
                        # Try to read as text first, fall back to binary if needed
                        try:
                            with open(v, 'r', encoding='utf-8') as f:
                                content = f.read()
                        except UnicodeDecodeError:
                            # File contains binary data, read as bytes and decode
                            with open(v, 'rb') as f:
                                content = f.read().decode('utf-8', errors='replace')
                        echo(f"Reading secret '{k}' from file '{v}'", fg='green')
                    except Exception as e:
                        echo(f"Error reading file '{v}': {str(e)}", fg='red')
                        continue
                else:
                    # Treat as literal value
                    content = v
            else:
                # No = sign, prompt for value
                k = s
                echo(f"Enter value for secret '{k}' (end with EOF / Ctrl-D):", fg='yellow')
                content = stdin.read()
            
            echo(f"Setting secret '{k}'", fg='white')
            run(['docker', 'secret', 'create', k, '-'], input=content,
                 stdout=stdout, stderr=stderr, universal_newlines=True, text=True, check=True)
                 
        except ValueError:
            echo(f"Error: Invalid format '{s}'. Use 'name=value', 'name=@filename', 'name=-', or just 'name'", fg='red')
            continue
        except Exception as e:
            echo(f"Error setting secret '{k}': {str(e)}", fg='red')
            continue


@command('secrets:rm')
@argument('secret', required=True)
def cmd_secrets_rm(secret):
    """Remove a secret"""
    if not require_swarm_or_warn():
        return
    call(['docker', 'secret', 'rm', secret], stdout=stdout, stderr=stderr, universal_newlines=True)


@command('secrets:ls')
def cmd_secrets_ls():
    """List docker secrets defined in host."""
    if not require_swarm_or_warn():
        return
    call(['docker', 'secret', 'ls'], stdout=stdout, stderr=stderr, universal_newlines=True)


@command('config:docker')
@argument('app')
def cmd_config_live(app):
    """Show live config for running app"""
    app = exit_if_invalid(app)
    config_file = join(APP_ROOT, app, DOCKER_COMPOSE)
    if exists(config_file):
        echo(open(config_file).read().strip(), fg='white')
    else:
        echo(f"Warning: app '{app}' not deployed, no config found.", fg='yellow')


@command('config:traefik')
@argument('app')
@option('--json', 'as_json', is_flag=True, help='Output labels as JSON')
def cmd_config_traefik(app, as_json=False):
    """Show generated Traefik labels for an app (from saved compose)."""
    app = exit_if_invalid(app)
    config_file = join(APP_ROOT, app, DOCKER_COMPOSE)
    if not exists(config_file):
        echo(f"Warning: app '{app}' not deployed, no config found.", fg='yellow')
        return
    try:
        cfg = safe_load(open(config_file, 'r', encoding='utf-8')) or {}
        services = cfg.get('services', {}) if isinstance(cfg, dict) else {}
        if not services:
            echo(f"Warning: no services found in compose for '{app}'.", fg='yellow')
            return
        if as_json:
            out = {}
            for name, svc in services.items():
                labels = svc.get('labels', {}) if isinstance(svc, dict) else {}
                deploy = svc.get('deploy', {}) if isinstance(svc, dict) else {}
                dlabels = deploy.get('labels', {}) if isinstance(deploy, dict) else {}
                out[name] = {
                    'labels': labels,
                    'deploy_labels': dlabels
                }
            echo(dumps(out, indent=2), fg='white')
            return
        for name, svc in services.items():
            echo(f"Service: {name}", fg='green')
            labels = svc.get('labels', {}) if isinstance(svc, dict) else {}
            if labels:
                echo("  labels:", fg='white')
                for k, v in labels.items():
                    echo(f"    {k}={v}", fg='white')
            deploy = svc.get('deploy', {}) if isinstance(svc, dict) else {}
            dlabels = deploy.get('labels', {}) if isinstance(deploy, dict) else {}
            if dlabels:
                echo("  deploy.labels:", fg='white')
                for k, v in dlabels.items():
                    echo(f"    {k}={v}", fg='white')
    except Exception as e:
        echo(f"Error reading Traefik config: {e}", fg='red')


@command('traefik:ls')
@argument('app')
def cmd_traefik_ls(app):
    """List Traefik routers/services for an app from saved compose."""
    app = exit_if_invalid(app)
    config_file = join(APP_ROOT, app, DOCKER_COMPOSE)
    if not exists(config_file):
        echo(f"Warning: app '{app}' not deployed, no config found.", fg='yellow')
        return
    try:
        cfg = safe_load(open(config_file, 'r', encoding='utf-8')) or {}
        services = cfg.get('services', {}) if isinstance(cfg, dict) else {}
        if not services:
            echo(f"Warning: no services found in compose for '{app}'.", fg='yellow')
            return
        for name, svc in services.items():
            labels = svc.get('labels', {}) if isinstance(svc, dict) else {}
            deploy = svc.get('deploy', {}) if isinstance(svc, dict) else {}
            dlabels = deploy.get('labels', {}) if isinstance(deploy, dict) else {}
            merged = {}
            merged.update(labels if isinstance(labels, dict) else {})
            merged.update(dlabels if isinstance(dlabels, dict) else {})
            routers = sorted([k for k in merged.keys() if k.startswith('traefik.http.routers.')])
            services_lbl = sorted([k for k in merged.keys() if k.startswith('traefik.http.services.')])
            if routers or services_lbl:
                echo(f"Service: {name}", fg='green')
                if routers:
                    echo("  routers:", fg='white')
                    for r in routers:
                        echo(f"    {r} = {merged[r]}", fg='white')
                if services_lbl:
                    echo("  services:", fg='white')
                    for s in services_lbl:
                        echo(f"    {s} = {merged[s]}", fg='white')
    except Exception as e:
        echo(f"Error listing Traefik routers/services: {e}", fg='red')


@command('traefik:inspect')
@argument('app')
def cmd_traefik_inspect(app):
    """Inspect the running Traefik service/container for an app."""
    app = exit_if_invalid(app)
    mode = get_app_mode(app)
    inspected = False
    if mode == 'swarm':
        svc_name = f"{app}_traefik"
        try:
            call(['docker', 'service', 'inspect', svc_name], stdout=stdout, stderr=stderr, universal_newlines=True)
            inspected = True
        except Exception:
            pass
    if not inspected:
        try:
            names = check_output(['docker', 'ps', '--format', '{{.Names}}'], universal_newlines=True).splitlines()
            target = next((n for n in names if n.startswith(f"{app}-traefik")), None)
            if target:
                call(['docker', 'inspect', target], stdout=stdout, stderr=stderr, universal_newlines=True)
                inspected = True
        except Exception:
            pass
    if not inspected:
        echo(f"Warning: could not find a running Traefik service/container for '{app}'.", fg='yellow')


@command('runtime:rebuild-all')
def cmd_runtime_rebuild_all():
    """Rebuild all built-in runtime images (python/nodejs/php/bun/static)."""
    ok = docker_rebuild_all_runtimes()
    if ok:
        echo("-----> Runtime images rebuilt successfully", fg='green')
    else:
        echo("Warning: one or more runtime images failed to rebuild", fg='yellow')


@command('runtime:rebuild')
@argument('runtime', required=True)
def cmd_runtime_rebuild(runtime):
    """Rebuild a single built-in runtime image (python/nodejs/php/bun/static)."""
    ok = docker_rebuild_runtime(runtime)
    if ok:
        echo(f"-----> Runtime '{runtime}' rebuilt successfully", fg='green')
    else:
        echo(f"Error: failed to rebuild runtime '{runtime}'", fg='red')


@command('runtime:clean')
def cmd_runtime_clean():
    """Remove all built-in runtime images (kata/*)."""
    docker_remove_runtime_images()
    echo("-----> Runtime images removed (kata/*)", fg='green')


@command('traefik:dashboard')
@option('--port', 'dash_port', default=8080, show_default=True, help='Host port to bind the Traefik dashboard.')
@option('--bind', 'dash_bind', default='127.0.0.1', show_default=True, help='Bind address for the dashboard (use 0.0.0.0 to expose externally).')
@option('--web', 'web_bind', default='80:80', show_default=True, help='Host bind for HTTP entrypoint (host:container). Set empty to skip binding.')
@option('--websecure', 'websecure_bind', default='443:443', show_default=True, help='Host bind for HTTPS entrypoint (host:container). Set empty to skip binding.')
@option('--off', is_flag=True, default=False, help='Disable the dashboard (recreate container without dashboard entrypoint).')
@option('--replace/--no-replace', default=True, show_default=True, help='Replace existing kata-traefik container if present.')
def cmd_traefik_dashboard(dash_port, dash_bind, web_bind, websecure_bind, off, replace):
    """Restart shared Traefik with the dashboard enabled or disable it with --off."""
    network_name = 'traefik-proxy'
    volume_name = 'traefik-acme'

    if not ensure_docker_network(network_name):
        return
    if not ensure_docker_volume(volume_name):
        return

    if replace:
        try:
            call(['docker', 'rm', '-f', 'kata-traefik'], stdout=stdout, stderr=stderr, universal_newlines=True)
        except Exception as exc:
            echo(f"Warning: could not remove existing kata-traefik: {exc}", fg='yellow')

    run_shared_traefik(
        enable_dashboard=not off,
        dashboard_bind=dash_bind,
        dashboard_port=dash_port,
        web_bind=web_bind,
        websecure_bind=websecure_bind
    )
    if off:
        echo("Traefik dashboard disabled (container restarted without dashboard)", fg='green')
    else:
        target = 'localhost' if dash_bind == '127.0.0.1' else dash_bind
        echo(f"Traefik dashboard enabled at http://{target}:{dash_port}/dashboard/", fg='green')


@command('rm')
@argument('app')
@option('--force', '-f', is_flag=True, help='Force destruction without confirmation')
@option('--wipe',  '-w', is_flag=True, help='Delete data and config directories')
def cmd_destroy(app, force, wipe):
    """Remove an app"""
    app = sanitize_app_name(app)
    app_path = join(APP_ROOT, app)
    if not exists(app_path):
        echo(f"Error: stack '{app}' not deployed!", fg='red')
        return

    if not force:
        response = input(f"Are you sure you want to destroy '{app}'? [y/N] ")
        if response.lower() != 'y':
            echo("Aborted.", fg='yellow')
            return

    do_remove(app)

    paths = [join(APP_ROOT, app), join(ENV_ROOT, app), join(LOG_ROOT, app), join(GIT_ROOT, app)]
    if wipe:
        paths.extend([join(DATA_ROOT, app), join(CONFIG_ROOT, app)])

    for path in paths:
        if exists(path):
            try:
                rmtree(path)
            except Exception as e:
                echo(f"Error removing {path}: {str(e)}", fg='red')
    echo(f"-----> '{app}' destroyed", fg='green')
    if not wipe:
        echo("Data and config directories were not deleted. Use --wipe to remove them.", fg='yellow')

@command('docker', add_help_option=False, context_settings=dict(ignore_unknown_options=True))
@argument('args', nargs=-1, required=True, type=UNPROCESSED)
def cmd_docker(args):
    """Pass-through Docker commands (logs, etc.)"""
    call(['docker'] + list(args),
         stdout=stdout, stderr=stderr, universal_newlines=True)


@command('docker:services')
@argument('stack', required=True)
def cmd_services(stack):
    """List services for a stack"""
    call(['docker', 'stack', 'services', stack],
         stdout=stdout, stderr=stderr, universal_newlines=True)


@command('ps')
@argument('service', nargs=-1, required=True)
def cmd_service_ps(service):
    """List processes for one or more services"""
    # First argument is treated as the app name; remaining (optional) are service filters
    app = sanitize_app_name(service[0])
    extras = list(service[1:])
    mode = get_app_mode(app)

    if mode == 'swarm':
        call(['docker', 'service', 'ps'] + ([f"{app}_{s}" for s in extras] if extras else [app]),
             stdout=stdout, stderr=stderr, universal_newlines=True)
        return

    # Compose mode
    compose_path = join(APP_ROOT, app, DOCKER_COMPOSE)
    if not exists(compose_path):
        echo(f"Error: compose file not found for app '{app}' at {compose_path}", fg='red')
        return
    call(get_compose_cmd() + ['-f', compose_path, 'ps'] + extras,
         stdout=stdout, stderr=stderr, universal_newlines=True)


@command('run')
@argument('service', required=True)
@argument('command', nargs=-1, required=True)
def cmd_run(service, command):
    """Run a command inside a service"""
    call(['docker', 'exec', '-ti', service] + list(command),
         stdout=stdout, stderr=stderr, universal_newlines=True)


@command('restart')
@argument('app')
def cmd_restart(app):
    """Restart an app"""
    app = exit_if_invalid(app)
    do_restart(app)


@command('mode')
@argument('app')
@argument('mode', required=False)
def cmd_mode(app, mode=None):
    """Get or set deployment mode for an app: compose|swarm"""
    app = exit_if_invalid(app)
    current = get_app_mode(app)
    if not mode:
        echo(f"{app}: {current}", fg='white')
        return
    if mode not in ('compose', 'swarm'):
        echo("Error: mode must be 'compose' or 'swarm'", fg='red')
        return
    if mode == 'swarm' and not docker_supports_swarm():
        echo("Error: Docker Swarm is not active; cannot set mode to 'swarm'", fg='red')
        return
    if mode == current:
        echo(f"Mode unchanged ({current})", fg='yellow')
        return
    set_app_mode(app, mode)
    echo(f"Set mode for '{app}' -> {mode}", fg='green')
    echo("Restarting to apply mode change...", fg='yellow')
    do_restart(app)


@command('stop')
@argument('app')
def cmd_stop(app):
    """Stop an app"""
    app = exit_if_invalid(app)
    do_stop(app)


@command('setup')
def cmd_setup():
    """Setup the local kata environment"""
    for f in ROOT_FOLDERS:
        d = globals()[f]
        if not exists(d):
            makedirs(d)
            echo(f"Created {d}", fg='green')
    echo("Kata setup complete", fg='green')


@command("setup:ssh")
@argument('public_key_file')
def cmd_setup_ssh(public_key_file):
    """Set up a new SSH key (use - for stdin)"""
    def add_helper(key_file):
        if exists(key_file):
            try:
                fingerprint = str(check_output('ssh-keygen -lf ' + key_file, shell=True)).split(' ', 4)[1]
                key = open(key_file, 'r').read().strip()
                echo("Adding key '{}'.".format(fingerprint), fg='white')
                setup_authorized_keys(fingerprint, KATA_SCRIPT, key)
            except Exception:
                echo("Error: invalid public key file '{}': {}".format(key_file, format_exc()), fg='red')
        elif public_key_file == '-':
            buffer = "".join(stdin.readlines())
            with NamedTemporaryFile(mode="w") as f:
                f.write(buffer)
                f.flush()
                add_helper(f.name)
        else:
            echo("Error: public key file '{}' not found.".format(key_file), fg='red')

    add_helper(public_key_file)


@command('update')
def cmd_update():
    """Update kata to the latest version"""
    try:
        # Download the latest version
        echo("Downloading latest version...", fg='green')
        parsed = urlparse(KATA_RAW_SOURCE_URL)
        conn = HTTPSConnection(parsed.netloc)
        conn.request('GET', parsed.path)
        resp = conn.getresponse()

        if resp.status == 200:
            body = resp.read().decode('utf-8')
            # Create a backup of the current script
            backup_file = f"{KATA_SCRIPT}.backup"
            copyfile(KATA_SCRIPT, backup_file)
            echo(f"Created backup at {backup_file}", fg='green')
            # Write the new version
            with open(KATA_SCRIPT, 'w', encoding='utf-8') as f:
                f.write(body)
            # Make it executable
            chmod(KATA_SCRIPT, S_IRUSR | S_IWUSR | S_IXUSR)
            echo("Update complete! Restart any running kata processes.", fg='green')
        else:
            echo(f"Failed to download update: HTTP {resp.status}", fg='red')
    except ImportError:
        echo("Error: requests module not installed", fg='red')
        echo("Install it with: pip install requests", fg='yellow')
    except Exception as e:
        echo(f"Error updating kata: {str(e)}", fg='red')

# === Internal commands ===

@command("git-hook", hidden=True)
@argument('app')
def cmd_git_hook(app):
    # INTERNAL: Post-receive git hook
    app = sanitize_app_name(app)
    repo_path = join(GIT_ROOT, app)
    app_path = join(APP_ROOT, app)
    data_path = join(DATA_ROOT, app)

    for line in stdin:
        oldrev, newrev, refname = line.strip().split(" ")
        if not exists(app_path):
            echo("-----> Creating app '{}'".format(app), fg='green')
            makedirs(app_path)
            if not exists(data_path):
                makedirs(data_path)
            call("git clone --quiet {} {}".format(repo_path, app), cwd=APP_ROOT, shell=True)
        do_deploy(app, newrev=newrev)


@command("git-receive-pack", hidden=True)
@argument('app')
def cmd_git_receive_pack(app):
    # INTERNAL: Handle git pushes for an app
    app = sanitize_app_name(app)
    hook_path = join(GIT_ROOT, app, 'hooks', 'post-receive')
    env = globals()
    env.update(locals())

    if not exists(hook_path):
        makedirs(dirname(hook_path))
        # Initialize the repository with a hook to this script
        call("git init --quiet --bare " + app, cwd=GIT_ROOT, shell=True)
        with open(hook_path, 'w', encoding='utf-8') as h:
            h.write("""#!/usr/bin/env bash
set -e; set -o pipefail;
cat | KATA_ROOT="{KATA_ROOT:s}" {KATA_SCRIPT:s} git-hook {app:s}""".format(**env))
        # Make the hook executable by our user
        chmod(hook_path, stat(hook_path).st_mode | S_IXUSR)
    # Handle the actual receive. We'll be called with 'git-hook' after it happens
    call('git-shell -c "{}" '.format(argv[1] + " '{}'".format(app)), cwd=GIT_ROOT, shell=True)


@command("git-upload-pack", hidden=True)
@argument('app')
def cmd_git_upload_pack(app):
    # INTERNAL: Handle git upload pack for an app
    app = sanitize_app_name(app)
    env = globals()
    env.update(locals())
    # Handle the actual receive. We'll be called with 'git-hook' after it happens
    call('git-shell -c "{}" '.format(argv[1] + " '{}'".format(app)), cwd=GIT_ROOT, shell=True)


@command("scp", context_settings=dict(ignore_unknown_options=True))
@argument('args', nargs=-1, required=True, type=UNPROCESSED)
def cmd_scp(args):
    """Copy files to/from the server"""
    call(["scp"] + list(args), cwd=abspath(environ['HOME']))


# Helper to print CLI help

def show_help():
    from click import Context
    ctx = Context(cli)
    echo(cli.get_help(ctx), fg='white')


@command("help")
def cmd_help():
    """Display help"""
    show_help()


if __name__ == '__main__':
    # Run the CLI with all registered commands
    cli()
