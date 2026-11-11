"""Real pipe/exit behavior behind a fake Docker boundary; no containers or agents."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('logfeed', Path(__file__).with_name('repo-logfeed.py'))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


class LogFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        (self.state / 'lease').touch()
        L.write(self.state / 'state.json', {'state': 'starting', 'token': 'mine', 'heartbeat': time.time()})
        for name, value in [('SIGTERM', signal.getsignal(signal.SIGTERM)), ('SIGINT', signal.getsignal(signal.SIGINT))]:
            self.addCleanup(signal.signal, getattr(signal, name), value)
        self.context = patch.object(L, 'context', return_value=(self.root, self.state, 'repo'))
        self.context.start()
        self.addCleanup(self.context.stop)

    def run_worker(self, code, prepared=True):
        popen = subprocess.Popen
        self.processes = []
        self.environments = []

        def fake_docker(argv, **kwargs):
            self.assertEqual(argv[:3], ['docker', 'compose', 'logs'])
            self.environments.append(kwargs['env'])
            proc = popen([sys.executable, '-c', code], **kwargs)
            self.processes.append(proc)
            return proc

        with patch.object(L.O, 'run', return_value=json.dumps({'COMPOSE_PROJECT_NAME': 'ours'})), \
             patch.object(L.O, 'prepared_environment', return_value=prepared), \
             patch.object(L.sp, 'Popen', side_effect=fake_docker):
            L.worker('demo', 'mine')
        return L.read(self.state / 'state.json')

    def test_nonzero_exit_is_error_and_keeps_final_output(self):
        status = self.run_worker("import sys; print('docker unavailable'); sys.exit(7)")
        self.assertEqual(status['state'], 'error')
        self.assertEqual(status['exit_code'], 7)
        self.assertIn('docker unavailable', status['logs'])
        self.assertEqual(self.processes[0].returncode, 7)

    def test_success_retains_bounded_tail_and_uses_verified_compose(self):
        with patch.dict(os.environ, {'COMPOSE_FILE': '/wrong/project', 'COMPOSE_PROJECT_NAME': 'wrong'}):
            status = self.run_worker("for i in range(4000): print(str(i) + 'x'*100)")
        self.assertEqual(status['state'], 'ended')
        self.assertEqual(status['exit_code'], 0)
        self.assertLessEqual(len(status['logs']), 180000)
        self.assertLessEqual(len(status['logs'].splitlines()), 1800)
        self.assertTrue(status['logs'].endswith('3999' + 'x'*100))
        self.assertNotIn('COMPOSE_FILE', self.environments[0])
        self.assertEqual(self.environments[0]['COMPOSE_PROJECT_NAME'], 'ours')

    def test_expired_lease_stops_and_reaps_process(self):
        os.utime(self.state / 'lease', (1, 1))
        status = self.run_worker('import time; time.sleep(60)')
        self.assertEqual(status['state'], 'paused')
        self.assertEqual(status['heartbeat'], 0)
        self.assertIsNotNone(self.processes[0].returncode)
        self.assertTrue(self.processes[0].stdout.closed)

    def test_unprepared_stack_never_starts_docker(self):
        status = self.run_worker('', prepared=False)
        self.assertEqual(status['state'], 'error')
        self.assertIn('not been prepared', status['message'])
        self.assertEqual(self.processes, [])

    def test_wrong_token_does_not_allocate_or_change_state(self):
        before = (self.state / 'state.json').read_bytes()
        with patch.object(L.selectors, 'DefaultSelector') as selector, patch.object(L.O, 'run') as run:
            L.worker('demo', 'wrong')
        selector.assert_not_called()
        run.assert_not_called()
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_live_worker_lock_prevents_relaunch_even_with_stale_heartbeat(self):
        L.write(self.state / 'state.json', {'state': 'following', 'heartbeat': 0})
        with (self.state / 'worker.lock').open('a') as lock, patch.object(L.O, 'inspect') as inspect:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = L.poll('demo')
        inspect.assert_not_called()
        self.assertEqual(result['state'], 'following')

    def test_error_cooldown_prevents_repeated_launches(self):
        L.write(self.state / 'state.json', {'state': 'error', 'heartbeat': time.time() - 20})
        with patch.object(L.O, 'inspect') as inspect:
            result = L.poll('demo')
        inspect.assert_not_called()
        self.assertEqual(result['state'], 'error')
