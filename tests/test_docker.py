"""Docker boundaries using saved files and fake hc replies; no Docker daemon."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from repo_compose import environment, prepared_environment

spec = importlib.util.spec_from_file_location('docker_controller', Path(__file__).with_name('repo-docker.py'))
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


class DockerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'compose.work.json'
        self.envfile = self.root / 'compose.env'
        (self.root / 'state.env').touch()
        self.values = {'COMPOSE_FILE': str(self.config), 'COMPOSE_ENV_FILES': str(self.envfile), 'COMPOSE_PROJECT_NAME': 'project'}
        self.ctx = dict(root=str(self.root), stream='demo', project='project', name='docker-project')
        self.row = dict(address='t1', state='live', cwd=str(self.root), name='docker-project', labels={
            'repo-tools.role': 'docker-start', 'repo-tools.stream': 'demo',
            'repo-tools.checkout': str(self.root), 'repo-docker.project': 'project'})

    def test_only_wholly_absent_generated_pair_is_unprepared(self):
        self.assertFalse(prepared_environment(self.values, self.root))
        self.config.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            prepared_environment(self.values, self.root)
        self.envfile.touch()
        self.assertTrue(prepared_environment(self.values, self.root))

    def test_broken_symlink_is_damage_not_empty_state(self):
        self.config.symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            prepared_environment(self.values, self.root)

    def test_custom_missing_config_is_left_for_compose_to_report(self):
        self.values['COMPOSE_FILE'] = 'custom.yml'
        self.assertTrue(prepared_environment(self.values, self.root))
        del self.values['COMPOSE_PROJECT_NAME']
        with self.assertRaisesRegex(RuntimeError, 'valid saved'):
            prepared_environment(self.values, self.root)

    def test_environment_filters_foreign_and_invalid_values(self):
        with patch.dict('os.environ', {'COMPOSE_FILE': 'foreign', 'PATH': 'preserved'}, clear=True):
            result = environment({'COMPOSE_PROJECT_NAME': 'ours', 'COMPOSE_FILE': None, 'PATH': 'injected'})
        self.assertEqual(result, {'PATH': 'preserved', 'COMPOSE_PROJECT_NAME': 'ours'})

    def test_start_reuses_live_operation_without_launch(self):
        with patch.object(D, 'latest', return_value=self.row), patch.object(D, 'hc', return_value={'text': 'building'}) as hc:
            result = D.start(self.ctx)
        self.assertEqual(result['state'], 'running')
        self.assertEqual(result['terminal'], 't1')
        self.assertEqual([call.args[0] for call in hc.call_args_list], ['read'])

    def test_lost_launch_response_adopts_verified_operation_once(self):
        with patch.object(D, 'latest', side_effect=[None, self.row]), \
             patch.object(D, 'hc', side_effect=[subprocess.TimeoutExpired('hc', 12), {'text': 'building'}]) as hc:
            result = D.start(self.ctx)
        self.assertEqual(result['terminal'], 't1')
        self.assertEqual([call.args[0] for call in hc.call_args_list], ['run', 'read'])
        argv = hc.call_args_list[0].args
        self.assertNotIn('--keep', argv)
        self.assertEqual(argv[-2:], ('_herdr-start', 'demo'))

    def test_unconfirmed_launch_does_not_replay_old_finished_operation(self):
        old = dict(self.row, state='finished', exit_code=0)
        with patch.object(D, 'latest', side_effect=[old, old]), \
             patch.object(D, 'hc', side_effect=RuntimeError('uncertain')) as hc:
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                D.start(self.ctx)
        self.assertEqual(hc.call_count, 1)

    def test_foreign_checkout_cannot_own_startup(self):
        foreign = dict(self.row, cwd=str(self.root / 'other'))
        with patch.object(D, 'hc', side_effect=[{'terminals': [foreign]}, foreign]):
            with self.assertRaisesRegex(RuntimeError, 'different command'):
                D.latest(self.ctx)
        foreign = dict(self.row, labels=dict(self.row['labels'], **{'repo-tools.checkout': '/other'}))
        self.assertFalse(D.belongs(foreign, self.ctx))

    def test_launch_reply_is_verified_before_adoption(self):
        foreign = dict(self.row, cwd='/other')
        with patch.object(D, 'latest', return_value=None), \
             patch.object(D, 'hc', side_effect=[{'address': 't1'}, foreign]):
            with self.assertRaisesRegex(RuntimeError, 'identity'):
                D.start(self.ctx)

    def test_snapshot_requires_numeric_zero_and_survives_read_failure(self):
        for code, expected in [(0, 'succeeded'), (1, 'failed'), (None, 'failed'), (False, 'failed')]:
            with self.subTest(code=code), patch.object(D, 'hc', side_effect=RuntimeError('offline')):
                result = D.snapshot(self.ctx, dict(self.row, state='finished', exit_code=code))
            self.assertEqual(result['state'], expected)
            self.assertIn('unavailable', result['output'])

    def test_inspection_failure_is_not_an_empty_stack(self):
        self.config.write_text('{}')
        self.envfile.touch()
        replies = [str(self.root), 'codex/demo', json.dumps(self.values), RuntimeError('daemon unavailable')]
        with patch.object(D.O, 'run', side_effect=replies) as run:
            with self.assertRaisesRegex(RuntimeError, 'daemon unavailable'):
                D.O.inspect('demo', status_only=True)
        self.assertEqual(run.call_args.args[0], ['docker', 'compose', 'ps', '--all', '--format', 'json'])

    def test_unprepared_inspection_never_contacts_docker(self):
        with patch.object(D.O, 'run', side_effect=[str(self.root), 'codex/demo', json.dumps(self.values)]) as run:
            result = D.O.inspect('demo', metrics=True)
        self.assertEqual(result['state'], 'unprepared')
        self.assertEqual(run.call_count, 3)
        self.assertEqual(result['services'], [])
