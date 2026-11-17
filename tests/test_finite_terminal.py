"""Finite jobs preserve diagnostics without spawning an unattended shell."""
import importlib.util
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name+'.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FiniteTerminal(unittest.TestCase):
    def test_review_returns_after_worker_even_in_terminal(self):
        r = module('repo-review')
        with patch.object(r.sys, 'argv', ['review','_pane','/tmp/review','token']), patch.object(r, 'worker') as worker, patch.object(r.os, 'execv') as shell, patch.object(r.sys.stdin, 'isatty', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            r.main()
        worker.assert_called_once_with(Path('/tmp/review'), 'token')
        shell.assert_not_called()

    def test_failed_workflow_keeps_failure_and_returns(self):
        f = module('repo-flow')
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            f.write(runtime/'state.json', {'token':'token','stream':'sample','state':'queued'})
            with patch.object(f, 'perform', side_effect=RuntimeError('check failed')), patch.object(f, 'command'), patch.object(f.os, 'execv') as shell, patch.object(f.sys.stdin, 'isatty', return_value=True), contextlib.redirect_stdout(io.StringIO()):
                f.worker(runtime,'token')
            job=f.read(runtime/'state.json')
            self.assertEqual(job['state'],'needs-you')
            self.assertIn('check failed',job['message'])
            shell.assert_not_called()

    def test_checkpoint_does_not_keep_or_delete_terminal_history(self):
        n=module('repo-new-conversation')
        with patch.object(n,'hc') as hc:
            n.launch_worker(Path('/tmp/project'),'sample',{'token':'token'})
        argv=hc.call_args.args
        self.assertNotIn('--keep',argv)
        self.assertNotIn('--rm',argv)
        self.assertIn('--worker',argv)
