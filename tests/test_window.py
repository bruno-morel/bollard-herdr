"""Window lifecycle tests never launch a real app or agent."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import window_helper as W

class Windows(unittest.TestCase):
    def test_long_stream_names_use_short_socket_safe_profile(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as d:
            root=Path(d)
            (root/'mods').mkdir()
            (root/'layouts').mkdir()
            tree={'children':[{'id':'portrait-bar','content':{'props':{}}},
                {'id':'portrait-streams','children':[{'id':'top-lane','children':[
                    {'id':'top-conversation'},{'id':'top-views'},{'id':'top-info'}]}]}]}
            W.save(root/'layouts/studio-work-portrait.json',tree)
            context=dict(cwd='/repo/worktrees/example',stream='example-'+'long-'*20+'stream',role='work',repo='long-repository-name',terminal='t1')
            destination,_=W.prepare(root,'top',context)
            self.assertTrue(destination.name.startswith('w-'))
            self.assertLess(len(os.fsencode(str(destination/'herdr-app.sock'))),104)
            self.assertEqual(W.prepare(root,'top',context)[0],destination)

    def test_existing_window_is_reused_without_spawning(self):
        with tempfile.TemporaryDirectory() as d, patch.object(W.shutil,'which',return_value='/fake/herdr'), patch.object(W.sp,'run',return_value=SimpleNamespace(returncode=0)), patch.object(W,'focus_context'), patch.object(W.sp,'Popen') as spawn:
            self.assertTrue(W.launch_window(Path(d),{'stream':'demo'})['opened'])
            spawn.assert_not_called()

    def test_live_unacknowledged_window_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(W.shutil,'which',return_value='/fake/herdr'), patch.object(W.sp,'run',return_value=SimpleNamespace(returncode=1)), patch.object(W.os,'kill'), patch.object(W.sp,'Popen') as spawn:
            W.save(Path(d)/'launch-process.json',{'pid':123})
            with self.assertRaisesRegex(RuntimeError,'no duplicate'):
                W.launch_window(Path(d),{'stream':'demo'})
            spawn.assert_not_called()

    def test_focus_uses_terminal_not_stale_tab_labels(self):
        with patch.object(W.sp, 'run') as run:
            W.focus_context('/fake/herdr', {}, {'terminal': 'host/t1'})
            self.assertEqual(run.call_count, 1)
            args = run.call_args.args[0]
            self.assertEqual(args[1:3], ['do', 'pane.focus'])
            self.assertEqual(json.loads(args[3]), {'terminal': 'host/t1'})
