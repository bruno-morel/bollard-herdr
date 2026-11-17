import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack
import subprocess


class ResumePrompt(unittest.TestCase):
    def test_resume_has_no_model_turn_but_new_and_explicit_tasks_do(self):
        spec = importlib.util.spec_from_file_location('resume_agent', Path(__file__).parent/'repo-agent.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        for provider in ('codex', 'claude', 'cursor'):
            for mode in ('new', 'resume', 'picker', 'task', 'take'):
                with self.subTest(provider=provider, mode=mode), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    pref = root/'state'/'work.agent'
                    pref.parent.mkdir()
                    packet = root/'handoff'
                    packet.mkdir()
                    (packet/'implementation.md').write_text('Existing handoff')
                    task = None
                    if mode == 'task':
                        task = pref.parent/'workflow'/'task.txt'
                        task.parent.mkdir()
                        task.write_text('Explicit implementation request')
                    if mode == 'take':
                        pref.with_suffix('.take').write_text(str(root))
                    resume = None if mode == 'new' else '' if mode == 'picker' else 'exact-chat-id'
                    with ExitStack() as stack:
                        for name, value in [('preferences', pref), ('executable', provider), ('packet', packet), ('context', None), ('prompt', 'FULL STARTUP')]:
                            stack.enter_context(patch.object(m, name, return_value=value))
                        stack.enter_context(patch.dict(m.os.environ, {}, clear=True))
                        launch = stack.enter_context(patch.object(m, 'run_foreground', return_value=subprocess.CompletedProcess([], 0)))
                        m.run_agent(root, 'example', 'work', provider, resume=resume, once=True, task_file=task)
                        args = launch.call_args.args[0]
                        self.assertFalse(any(x is None for x in args))
                        if mode in ('resume', 'picker'):
                            self.assertNotIn('FULL STARTUP', args)
                            m.prompt.assert_not_called()
                        else:
                            self.assertTrue(any('FULL STARTUP' in x for x in args))
                        if resume:
                            self.assertIn('exact-chat-id', args)
                        self.assertNotIn('--last', args)
