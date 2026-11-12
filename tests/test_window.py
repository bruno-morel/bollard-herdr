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

    def test_attention_matches_exact_window_before_stream_and_ignores_unmanaged(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();child=root/'screens/w-child';child.mkdir(parents=True)
            W.save(root/'shared.json',{'repo.portrait.lanes':{'top':dict(cwd='/repo',stream='demo',role='work',on='box',terminal='box/t1')}})
            W.save(child/'repo-window.json',dict(origin=str(root)))
            W.save(child/'shared.json',{'repo.portrait.lanes':{'bottom':dict(terminal='box/old')},'repo.portrait.displayed':{'bottom':dict(cwd='/repo',stream='demo',role='work',on='box',terminal='box/t2')}})
            (root/'screens/a.lock').touch()
            ctx=dict(cwd='/repo',stream='demo',role='work',on='box',terminal='box/t2')
            with patch.object(Path,'is_socket',return_value=True):
                matches=W.agent_windows(root,ctx)
            self.assertEqual(matches[0][1],child)
            self.assertTrue(matches[0][3])
            self.assertEqual(len(matches),2)

    def test_attention_focus_never_launches_window_or_agent(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)
            with patch.object(W,'agent_windows',return_value=[(0,home,'top',True)]),patch.object(W.shutil,'which',return_value='/fake/herdr'),patch.object(W.sp,'run',return_value=SimpleNamespace(returncode=0)) as run,patch.object(W,'activate_window') as activate,patch.object(W.sp,'Popen') as spawn:
                result=W.focus_agent(home,{'terminal':'box/t2'})
            self.assertTrue(result['found']);spawn.assert_not_called();activate.assert_called_once_with(home)
            self.assertIn('repo-portrait.attention-focus:',run.call_args.args[0][2])

    def test_attention_without_open_window_returns_fallback(self):
        with patch.object(W,'agent_windows',return_value=[]),patch.object(W.shutil,'which',return_value='/fake/herdr'),patch.object(W.sp,'Popen') as spawn:
            self.assertFalse(W.focus_agent(Path('/app'),{'terminal':'box/t2'})['found'])
            spawn.assert_not_called()
