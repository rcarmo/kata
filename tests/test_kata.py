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
             patch("time.sleep", return_value=None):
            self.assertFalse(kata.wait_stack_removed("app", timeout=0))


if __name__ == "__main__":
    unittest.main()
