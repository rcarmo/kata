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


if __name__ == "__main__":
    unittest.main()
