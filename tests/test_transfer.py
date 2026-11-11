"""Transfer snapshots between disposable repositories, without launching agents."""
from argparse import Namespace
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('transfer', Path(__file__).with_name('repo-transfer.py'))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.src, self.dest = self.base / 'source', self.base / 'destination'
        self.target = self.base / 'destination-worktrees/demo'
        for root in (self.src, self.dest):
            root.mkdir()
            self.git(root, 'init', '-q')
            self.git(root, 'config', 'user.email', 'test@example.invalid')
            self.git(root, 'config', 'user.name', 'Test')
            (root / 'README.md').write_text('base\n')
            self.git(root, 'add', '.')
            self.git(root, 'commit', '-qm', 'base')
            self.git(root, 'branch', '-M', 'main')
        self.git(self.src, 'checkout', '-qb', 'codex/demo')
        self.packet = self.src / 'docs/handoffs/demo'
        self.packet.mkdir(parents=True)
        (self.packet / 'brief.md').write_text('Keep this brief\n')
        (self.packet / 'implementation.md').write_text('Historical implementation\n')
        other = self.src / 'docs/handoffs/other'
        other.mkdir()
        (other / 'brief.md').write_text('Not part of this transfer\n')
        self.old_cwd = Path.cwd()
        os.chdir(self.src)
        self.addCleanup(os.chdir, self.old_cwd)
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME': str(self.base / 'runtime')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.output = io.StringIO()
        self.prepare = []

    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()

    def transfer(self, apply=False, prepare_error=False):
        run = subprocess.run

        def boundary(argv, **kwargs):
            if argv[0] == str(T.BIN / 'work'):
                self.prepare.append((argv, kwargs))
                if prepare_error:
                    raise subprocess.CalledProcessError(1, argv)
                return subprocess.CompletedProcess(argv, 0)
            return run(argv, **kwargs)

        with patch.object(T.sp, 'run', side_effect=boundary), redirect_stdout(self.output):
            T.transfer(Namespace(stream='demo', destination=str(self.dest), source_base=None, include=[], apply=apply))

    def test_preview_creates_nothing(self):
        before = self.git(self.src, 'status', '--porcelain')
        self.transfer()
        self.assertFalse(self.target.exists())
        self.assertFalse((self.dest / 'docs').exists())
        self.assertEqual(self.git(self.dest, 'branch', '--list', 'codex/demo'), '')
        self.assertEqual(self.git(self.src, 'status', '--porcelain'), before)
        self.assertEqual(self.prepare, [])
        self.assertIn('Preview only', self.output.getvalue())

    def test_apply_preserves_brief_and_source_and_marks_old_implementation(self):
        before = self.git(self.src, 'status', '--porcelain')
        self.transfer(apply=True)
        packet = self.target / 'docs/handoffs/demo'
        self.assertEqual((packet / 'brief.md').read_text(), 'Keep this brief\n')
        self.assertEqual((packet / 'original-implementation.md').read_text(), 'Historical implementation\n')
        self.assertIn('snapshot, not a migrated agent conversation', (packet / 'implementation.md').read_text())
        self.assertEqual((packet / 'branch.txt').read_text(), 'codex/demo\n')
        self.assertFalse((self.target / 'docs/handoffs/other').exists())
        self.assertEqual(self.git(self.target, 'check-ignore', 'scratch/probe'), 'scratch/probe')
        self.assertEqual(self.git(self.src, 'status', '--porcelain'), before)
        self.assertEqual(self.git(self.dest, 'status', '--porcelain'), '')
        self.assertEqual(self.git(self.target, 'rev-parse', 'HEAD'), self.git(self.dest, 'rev-parse', 'HEAD'))
        self.assertEqual(len(self.prepare), 1)
        self.assertIn('Ready to review:', self.output.getvalue())

    def test_conflict_refuses_before_worktree_creation(self):
        path = self.dest / 'docs/handoffs/demo/brief.md'
        path.parent.mkdir(parents=True)
        path.write_text('Destination owns this\n')
        self.git(self.dest, 'add', '.')
        self.git(self.dest, 'commit', '-qm', 'destination brief')
        with self.assertRaisesRegex(RuntimeError, 'destination conflict'):
            self.transfer(apply=True)
        self.assertFalse(self.target.exists())
        self.assertEqual(path.read_text(), 'Destination owns this\n')

    def test_source_symlink_is_not_copied(self):
        (self.packet / 'linked.md').symlink_to(self.src / 'README.md')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.transfer(apply=True)
        self.assertFalse(self.target.exists())

    def test_prepare_failure_keeps_recoverable_worktree_without_ready_claim(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.transfer(apply=True, prepare_error=True)
        self.assertEqual(self.git(self.target, 'branch', '--show-current'), 'codex/demo')
        self.assertTrue((self.target / 'docs/handoffs/demo/transfer.md').is_file())
        self.assertIn('retained if a later step fails', self.output.getvalue())
        self.assertNotIn('Ready to review:', self.output.getvalue())

    def test_init_preserves_existing_instructions_and_is_idempotent(self):
        (self.dest / 'docs').mkdir()
        (self.dest / 'docs/REPO-WORKFLOW.md').write_text('Project-specific workflow\n')
        (self.dest / 'AGENTS.md').write_text('Project-specific instructions\n')
        T.layout(self.dest, apply=True, preserve_existing=True)
        first = (self.dest / 'AGENTS.md').read_text()
        T.layout(self.dest, apply=True, preserve_existing=True)
        self.assertEqual((self.dest / 'AGENTS.md').read_text(), first)
        self.assertIn('Project-specific instructions', first)
        self.assertEqual((self.dest / 'docs/REPO-WORKFLOW.md').read_text(), 'Project-specific workflow\n')
        self.assertEqual((self.dest / '.gitignore').read_text().count('/scratch/'), 1)
