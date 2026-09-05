import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


if not importlib.util.find_spec("click") or not importlib.util.find_spec("yaml"):
    raise unittest.SkipTest("kata runtime dependencies (click, pyyaml) are not installed")

os.environ.setdefault("KATA_ROOT", "/tmp/kata-tests")

import kata  # noqa: E402


class DockerNameValidationTests(unittest.TestCase):
    def test_valid_docker_names(self):
        for name in ["secret", "secret_1", "secret-1", "secret.name", "A1._-x"]:
            with self.subTest(name=name):
                self.assertTrue(kata.is_valid_docker_name(name))

    def test_invalid_docker_names(self):
        for name in ["", "-secret", ".secret", "_secret", "secret/name", "secret name", "secret;rm"]:
            with self.subTest(name=name):
                self.assertFalse(kata.is_valid_docker_name(name))


class SwarmDrainTests(unittest.TestCase):
    def test_wait_stack_removed_returns_true_when_no_resources_remain(self):
        with patch.object(kata, "check_output", return_value=""):
            self.assertTrue(kata.wait_stack_removed("app", timeout=1))

    def test_wait_stack_removed_returns_false_when_resources_remain(self):
        with patch.object(kata, "check_output", return_value="still-there"), \
             patch("time.sleep", return_value=None), \
             patch.object(kata, "echo"):
            self.assertFalse(kata.wait_stack_removed("app", timeout=0))


class LifecycleErrorHandlingTests(unittest.TestCase):
    def test_restart_stops_when_stop_fails(self):
        with patch.object(kata, "get_app_mode", return_value="compose"), \
             patch.object(kata, "do_stop", return_value=False), \
             patch.object(kata, "do_start") as do_start:
            self.assertFalse(kata.do_restart("app"))
            do_start.assert_not_called()

    def test_restart_stops_when_swarm_drain_fails(self):
        with patch.object(kata, "get_app_mode", return_value="swarm"), \
             patch.object(kata, "do_stop", return_value=True), \
             patch.object(kata, "wait_stack_removed", return_value=False), \
             patch.object(kata, "echo"), \
             patch.object(kata, "do_start") as do_start:
            self.assertFalse(kata.do_restart("app"))
            do_start.assert_not_called()


class AuditRegressionTests(unittest.TestCase):
    def test_drain_query_error_fails_closed(self):
        with patch.object(kata, 'check_output', side_effect=OSError('offline')):
            self.assertFalse(kata.wait_stack_removed('app'))

    def test_drain_uses_namespace_for_networks(self):
        with patch.object(kata, 'check_output', return_value='') as query:
            self.assertTrue(kata.wait_stack_removed('app'))
            self.assertIn('label=com.docker.stack.namespace=app', query.call_args.args[0])

    def test_restart_cli_failure_is_nonzero(self):
        from click.testing import CliRunner
        with patch.object(kata, 'exit_if_invalid', return_value='app'), \
             patch.object(kata, 'do_restart', return_value=False):
            result = CliRunner().invoke(kata.cli, ['restart', 'app'])
            self.assertEqual(result.exit_code, 1)

    def test_no_implicit_raw_container_fallback(self):
        from click.testing import CliRunner
        with patch.object(kata, 'exit_if_invalid', return_value='app'), \
             patch.object(kata, 'resolve_containers', return_value=[]), \
             patch.object(kata, 'call') as execute:
            result = CliRunner().invoke(kata.cli, ['run', 'app', 'db', 'sh'])
            self.assertEqual(result.exit_code, 1)
            execute.assert_not_called()

    def test_update_preserves_mode_and_backup(self):
        from click.testing import CliRunner
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            script = Path(directory) / 'kata.py'
            old = '#!/usr/bin/env python3\nprint("old")\n'
            new = '#!/usr/bin/env python3\nprint("new")\n'
            script.write_text(old)
            script.chmod(0o755)
            with patch.object(kata, 'KATA_SCRIPT', str(script)), \
                 patch.object(kata, '_http_get', return_value=new):
                result = CliRunner().invoke(kata.cli, ['update', '--no-restart'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(script.read_text(), new)
            self.assertEqual(Path(str(script) + '.backup').read_text(), old)
            self.assertEqual(script.stat().st_mode & 0o777, 0o755)

    def test_update_backup_failure_preserves_original(self):
        from click.testing import CliRunner
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            script = Path(directory) / 'kata.py'
            script.write_text('#!/usr/bin/env python3\n')
            with patch.object(kata, 'KATA_SCRIPT', str(script)), \
                 patch.object(kata, '_http_get', return_value='#!/usr/bin/env python3\npass\n'), \
                 patch.object(kata, 'copyfile', side_effect=OSError('denied')):
                result = CliRunner().invoke(kata.cli, ['update', '--no-restart'])
            self.assertEqual(result.exit_code, 1)
            self.assertEqual(script.read_text(), '#!/usr/bin/env python3\n')
            self.assertEqual(list(Path(directory).iterdir()), [script])


class RemainingAuditTests(unittest.TestCase):
    def test_binary_secret_is_not_decoded(self):
        from tempfile import TemporaryDirectory
        from click.testing import CliRunner
        with TemporaryDirectory() as directory:
            secret = Path(directory) / 'secret'
            secret.write_bytes(b'\xff\x00\r\n')
            with patch.object(kata, 'require_swarm_or_warn', return_value=True), \
                 patch.object(kata, 'run') as execute:
                result = CliRunner().invoke(kata.cli, ['secrets:set', f'key=@{secret}'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(execute.call_args.kwargs['input'], b'\xff\x00\r\n')

    def test_mode_stops_old_mode_before_saving_new(self):
        from click.testing import CliRunner
        events = []
        with patch.object(kata, 'exit_if_invalid', return_value='app'), \
             patch.object(kata, 'get_app_mode', return_value='swarm'), \
             patch.object(kata, 'do_stop', side_effect=lambda app: events.append('stop') or True), \
             patch.object(kata, 'wait_stack_removed', side_effect=lambda app: events.append('drain') or True), \
             patch.object(kata, 'set_app_mode', side_effect=lambda *args: events.append('save')), \
             patch.object(kata, 'do_start', side_effect=lambda app: events.append('start') or True):
            result = CliRunner().invoke(kata.cli, ['mode', 'app', 'compose'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(events, ['stop', 'drain', 'save', 'start'])

    def test_git_failure_prevents_deploy(self):
        with patch.object(kata, 'exists', return_value=True), \
             patch.object(kata, 'call', return_value=1), \
             patch.object(kata, 'parse_compose') as parse:
            self.assertFalse(kata.do_deploy('app'))
            parse.assert_not_called()

    def test_deleted_git_ref_does_not_deploy(self):
        from tempfile import TemporaryDirectory
        from click.testing import CliRunner
        with TemporaryDirectory() as directory:
            (Path(directory) / 'app').mkdir()
            with patch.object(kata, 'GIT_ROOT', directory), \
                 patch.object(kata, 'do_deploy') as deploy:
                result = CliRunner().invoke(kata.cli, ['git-hook', 'app'],
                    input='a' * 40 + ' ' + '0' * 40 + ' refs/heads/main\n')
            self.assertEqual(result.exit_code, 0, result.output)
            deploy.assert_not_called()
            self.assertTrue((Path(directory) / 'app' / 'kata-deploy.lock').exists())


class CleanupAuditTests(unittest.TestCase):
    def test_invalid_app_names_are_not_silently_rewritten(self):
        for name in ['', '../', 'app/name', '-option', 'app.name']:
            with self.subTest(name=name), self.assertRaises(SystemExit):
                kata.sanitize_app_name(name)

    def test_symlinked_app_is_rejected_before_stop(self):
        from tempfile import TemporaryDirectory
        from click.testing import CliRunner
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'apps').mkdir()
            (root / 'outside').mkdir()
            (root / 'apps' / 'app').symlink_to(root / 'outside')
            with patch.object(kata, 'APP_ROOT', str(root / 'apps')), \
                 patch.object(kata, 'do_remove') as remove:
                result = CliRunner().invoke(kata.cli, ['rm', 'app', '--force'])
            self.assertEqual(result.exit_code, 1, result.output)
            remove.assert_not_called()
            self.assertTrue((root / 'outside').exists())

    def test_failed_cleanup_never_reports_destroyed(self):
        from tempfile import TemporaryDirectory
        from click.testing import CliRunner
        from contextlib import ExitStack
        with TemporaryDirectory() as directory, ExitStack() as patches:
            for key in kata.ROOT_FOLDERS:
                root = Path(directory) / key
                (root / 'app').mkdir(parents=True)
                patches.enter_context(patch.object(kata, key, str(root)))
            patches.enter_context(patch.object(kata, 'do_remove', return_value=True))
            patches.enter_context(patch.object(kata, 'get_app_mode', return_value='compose'))
            patches.enter_context(patch.object(kata, 'call', return_value=1))
            result = CliRunner().invoke(kata.cli, ['rm', 'app', '--force'])
            self.assertEqual(result.exit_code, 1)
            self.assertNotIn("'app' destroyed", result.output)

    def test_docker_passthrough_preserves_failure(self):
        from click.testing import CliRunner
        with patch.object(kata, 'call', return_value=7):
            result = CliRunner().invoke(kata.cli, ['docker', 'info'])
        self.assertEqual(result.exit_code, 7)


class SSHCommandTests(unittest.TestCase):
    def test_logs_propagates_failure(self):
        from click.testing import CliRunner
        with patch.object(kata, 'exit_if_invalid', return_value='app'), \
             patch.object(kata, 'get_app_mode', return_value='swarm'), \
             patch.object(kata, 'call', return_value=5):
            result = CliRunner().invoke(kata.cli, ['logs', 'app', 'web'])
        self.assertEqual(result.exit_code, 5)

    def test_swarm_ps_without_service_uses_stack(self):
        from click.testing import CliRunner
        with patch.object(kata, 'get_app_mode', return_value='swarm'), \
             patch.object(kata, 'call', return_value=0) as execute:
            result = CliRunner().invoke(kata.cli, ['ps', 'app'])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(execute.call_args.args[0], ['docker', 'stack', 'ps', 'app'])

    def test_checked_call_reports_missing_executable(self):
        with patch.object(kata, 'call', side_effect=FileNotFoundError('missing')):
            with self.assertRaises(SystemExit) as result:
                kata.checked_call(['docker', 'info'])
        self.assertEqual(result.exception.code, 1)


class RuntimeAuditTests(unittest.TestCase):
    def test_image_removal_failure_is_false(self):
        with patch.object(kata, 'call', return_value=1):
            self.assertFalse(kata.docker_remove_image('kata/python'))

    def test_tempfile_creation_failure_is_reported_without_unbound_variable(self):
        with patch.object(kata, 'NamedTemporaryFile', side_effect=OSError('denied')):
            self.assertFalse(kata.docker_create_runtime_image('kata/test', 'FROM scratch'))

    def test_rebuild_cli_failure_exits_nonzero(self):
        from click.testing import CliRunner
        with patch.object(kata, 'docker_rebuild_runtime', return_value=False):
            result = CliRunner().invoke(kata.cli, ['runtime:rebuild', 'python'])
        self.assertEqual(result.exit_code, 1)

    def test_runtime_clean_failure_does_not_claim_success(self):
        from click.testing import CliRunner
        with patch.object(kata, 'docker_remove_runtime_images', return_value=False):
            result = CliRunner().invoke(kata.cli, ['runtime:clean'])
        self.assertEqual(result.exit_code, 1)
        self.assertNotIn('Runtime images removed', result.output)


class ParserAuditTests(unittest.TestCase):
    def parse(self, service):
        data = {'services': {'web': service}, 'volumes': {}}
        with patch.object(kata, 'load_yaml', return_value=data), \
             patch.object(kata, 'base_env', return_value={'TEST': 'value'}), \
             patch.object(kata, 'docker_handle_runtime_environment') as prepare:
            result, _ = kata.parse_compose('app', 'unused')
        return result['services']['web'], prepare

    def test_image_default_command_still_merges_environment(self):
        service, _ = self.parse({'image': 'alpine', 'environment': ['OWN=yes']})
        self.assertEqual(service['environment'], {'OWN': 'yes', 'TEST': 'value'})

    def test_explicit_image_consumes_runtime_without_preparing(self):
        service, prepare = self.parse({'image': 'alpine', 'runtime': 'python'})
        self.assertNotIn('runtime', service)
        prepare.assert_not_called()
        self.assertNotIn('volumes', service)

    def test_static_shorthand_prepares_image_and_mounts(self):
        service, prepare = self.parse({'static': True})
        self.assertEqual(service['image'], 'kata/static')
        self.assertIn('app:/app', service['volumes'])
        prepare.assert_called_once_with('app', 'static', env={'TEST': 'value'})
        self.assertNotIn('static', service)


class ExampleConfigurationTests(unittest.TestCase):
    def test_all_examples_parse_without_runtime_extensions_in_output(self):
        from tempfile import TemporaryDirectory
        from contextlib import ExitStack
        examples = sorted((REPO / 'docs/examples').glob('*/kata-compose.yaml'))
        self.assertEqual(len(examples), 8)
        with TemporaryDirectory() as root, ExitStack() as patches:
            for name in kata.ROOT_FOLDERS:
                patches.enter_context(patch.object(kata, name, str(Path(root) / name)))
            patches.enter_context(patch.object(kata, 'docker_handle_runtime_environment'))
            patches.enter_context(patch.object(kata, 'traefik_is_running', return_value=True))
            patches.enter_context(patch.object(kata, 'echo'))
            for path in examples:
                with self.subTest(example=path.parent.name):
                    data, _ = kata.parse_compose(path.parent.name, str(path))
                    self.assertTrue(data['services'])
                    for service in data['services'].values():
                        self.assertNotIn('runtime', service)
                        self.assertNotIn('static', service)
                    self.assertTrue(kata.safe_dump(data))


if __name__ == "__main__":
    unittest.main()
