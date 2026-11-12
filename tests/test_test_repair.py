import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('repair_tests',Path(__file__).with_name('repo-tests.py'))
T=importlib.util.module_from_spec(spec);spec.loader.exec_module(T)

class RepairDelivery(unittest.TestCase):
    def test_idle_delivery_busy_rejection_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ctx=(root,'demo',root/'runtime',root/'review',root/'packet','key')
            row={'state':'live','status':{'state':'working','app':'codex'},'labels':{
                'repo-tools.repo':'key','repo-tools.stream':'demo','repo-tools.role':'work','repo-tools.checkout':str(root)}}
            evidence=dict(stream='demo',root=str(root),state='stale',token='run',head='abc',results=[dict(id='browser',exit_code=1,argv=['test'],log='log')])
            calls=[]
            def hc(*args):
                calls.append(args)
                return row if args[0]=='get' else {'started':True}
            with patch.object(T,'hc',hc),patch.object(T,'active_guard'),patch.object(T,'agent_running',return_value=True),patch.object(T,'snapshot',return_value=evidence):
                with self.assertRaisesRegex(RuntimeError,'busy'):T.send(ctx,'t1',repair=True)
                self.assertFalse(any(c[0]=='send' for c in calls))
                row['status']['state']='idle'
                T.send(ctx,'t1',repair=True)
                sent=[c for c in calls if c[0]=='send']
                self.assertEqual(len(sent),1)
                self.assertEqual(sent[0][3:5],('--if','idle'))
                self.assertIn('verify the current failure',sent[0][2])
                self.assertIn('Do not start helpers, call Claude',sent[0][2])
                with self.assertRaisesRegex(RuntimeError,'already submitted'):T.send(ctx,'t1',repair=True)
                self.assertEqual(len([c for c in calls if c[0]=='send']),1)
                evidence['state']='running'
                with self.assertRaisesRegex(RuntimeError,'test run'):T.send(ctx,'t1',repair=True)
