"""Run the recovery CLI against real local Git remotes; no network or agents."""
import os
from pathlib import Path
import subprocess as sp
import tempfile
import unittest

RECOVER = Path(__file__).with_name('work-recover.py')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.root / 'README.md').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.git('branch', '-M', 'main')
        self.origin = self.base / 'origin.git'
        sp.run(['git', 'clone', '--bare', str(self.root), str(self.origin)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(self.origin))
        self.runtime = self.base / 'state/repo-tools'
        self.state = self.runtime / 'work/key'
        self.trees = self.base / 'repo-worktrees'
        self.target = self.trees / 'demo'
        self.record = self.state / 'demo/state.env'

    def git(self, *args):
        return sp.check_output(['git', '-C', str(self.root), *args], stderr=sp.PIPE).decode().strip()

    def recover(self, existing=False):
        result = sp.run([os.sys.executable, str(RECOVER), str(self.root), str(self.state), str(self.trees), str(self.runtime), 'demo', *(['--existing-only'] if existing else [])], capture_output=True, text=True)
        return result

    def existing_tree(self):
        self.git('worktree', 'add', '-b', 'codex/demo', str(self.target), 'main')

    def test_new_stream_uses_origin_main_and_writes_private_state(self):
        result = self.recover()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('-C', str(self.target), 'branch', '--show-current'), 'codex/demo')
        self.assertEqual(self.git('-C', str(self.target), 'rev-parse', 'HEAD'), self.git('rev-parse', 'main'))
        self.assertEqual(self.git('-C', str(self.target), 'check-ignore', 'scratch/probe'), 'scratch/probe')
        self.assertEqual(self.record.stat().st_mode & 0o777, 0o600)
        self.assertIn('SLOT=1\n', self.record.read_text())
        before = self.record.read_bytes()
        self.assertEqual(self.recover(existing=True).returncode, 0)
        self.assertEqual(self.record.read_bytes(), before)

    def test_existing_only_does_not_invent_branch(self):
        result = self.recover(existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no replacement created', result.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.record.exists())

    def test_cached_remote_branch_recovers_offline(self):
        self.git('update-ref', 'refs/remotes/origin/codex/demo', 'main')
        self.git('remote', 'set-url', 'origin', str(self.base / 'absent.git'))
        result = self.recover(existing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no network required', result.stderr)

    def test_unreachable_origin_does_not_create_replacement(self):
        self.git('remote', 'set-url', 'origin', str(self.base / 'absent.git'))
        result = self.recover()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no branch was created', result.stderr)
        self.assertEqual(self.git('branch', '--list', 'codex/demo'), '')
        self.assertFalse(self.target.exists())

    def test_existing_dirty_checkout_is_reused_unchanged(self):
        self.existing_tree()
        (self.target / 'README.md').write_text('uncommitted work\n')
        result = self.recover(existing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.target / 'README.md').read_text(), 'uncommitted work\n')
        self.assertIn('Recovering existing checkout', result.stderr)

    def test_registered_missing_checkout_is_not_recreated(self):
        self.existing_tree()
        self.target.rename(self.base / 'moved')
        before = self.git('worktree', 'list', '--porcelain')
        result = self.recover(existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('metadata was preserved', result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.git('worktree', 'list', '--porcelain'), before)

    def test_saved_checkout_on_wrong_branch_is_refused(self):
        self.assertEqual(self.recover().returncode, 0)
        before = self.record.read_bytes()
        self.git('-C', str(self.target), 'checkout', '-qb', 'other')
        result = self.recover(existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nothing changed', result.stderr)
        self.assertEqual(self.record.read_bytes(), before)

    def test_scratch_symlink_is_not_accepted_as_ready(self):
        self.existing_tree()
        outside = self.base / 'outside'
        outside.mkdir()
        (self.target / 'scratch').symlink_to(outside)
        result = self.recover(existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('real directory', result.stderr)
        self.assertFalse(self.record.exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_tracked_scratch_is_refused_even_with_saved_state(self):
        self.assertEqual(self.recover().returncode, 0)
        before = self.record.read_bytes()
        (self.target / 'scratch/keep.txt').write_text('tracked\n')
        self.git('-C', str(self.target), 'add', '-f', 'scratch/keep.txt')
        result = self.recover(existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('tracked files', result.stderr)
        self.assertEqual(self.record.read_bytes(), before)
