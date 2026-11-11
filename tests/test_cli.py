"""Exercise the real shell entry points, without Docker, agents or sessions."""
import os
from pathlib import Path
import subprocess as sp
import tempfile
import unittest

BIN = Path(__file__).resolve().parent


class CommandBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, HOME=str(self.root),
                        XDG_STATE_HOME=str(self.root / 'state'))

    def invoke(self, command, *args):
        return sp.run(['zsh', str(BIN / command), *args], cwd=self.root,
                      env=self.env, text=True, capture_output=True, timeout=5)

    def test_help_outside_repository_has_no_side_effects(self):
        for command in ('studio', 'work'):
            with self.subTest(command=command):
                result = self.invoke(command, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(command, result.stdout.lower())
                self.assertEqual(list(self.root.iterdir()), [])

    def test_open_outside_repository_fails_before_state_creation(self):
        for command in ('studio', 'work'):
            with self.subTest(command=command):
                result = self.invoke(command, 'open', 'example')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Git-controlled source tree', result.stderr)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_bare_repository_is_not_a_source_checkout(self):
        sp.run(['git', 'init', '--bare', '-q', str(self.root)], check=True)
        for command in ('studio', 'work'):
            result = self.invoke(command, 'open', 'example')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Git-controlled source tree', result.stderr)
            self.assertFalse((self.root / 'state').exists())
