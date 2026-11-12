import json
import os
import subprocess as sp
import unittest
from unittest.mock import patch
import repo_terminal_display as D

class TerminalDisplayTests(unittest.TestCase):
    def test_no_viewer_retains_cli(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(D.sp, 'run') as run:
            D.launch(['hc','run','--bg','--','agent'], cwd='/repo')
            run.assert_called_once_with(['hc','run','--bg','--','agent'], cwd='/repo')

    def test_palette_and_identity_reach_startup_and_nested_workers(self):
        for bg,fg in [('#ffffff','#202020'),('#181818','#eeeeee')]:
            palette={'bg':bg,'fg':fg}
            with patch.dict(os.environ,{D.ENV:json.dumps(palette)}), patch.object(D.sp,'run',return_value=sp.CompletedProcess([],0,'{"id":1,"result":{}}\n','')) as run:
                D.launch(['hc','run','--bg','--keep','--no-parent','--name','stream','--cwd','/repo with spaces','--label','repo-tools.role=studio','--','python3','launcher','--resume','saved-id'])
                p=json.loads(run.call_args.kwargs['input'])['params']
                self.assertEqual(p['display'],palette)
                self.assertEqual(json.loads(p['env'][D.ENV]),palette)
                self.assertEqual(p['argv'][-2:],['--resume','saved-id'])
                self.assertEqual(p['cwd'],'/repo with spaces')
                self.assertEqual(p['labels'],{'repo-tools.role':'studio'})
                self.assertTrue(p['keep']);self.assertTrue(p['no_parent'])

    def test_invalid_or_uncertain_launch_never_falls_back(self):
        with patch.dict(os.environ,{D.ENV:'{"bg":"bad"}'}), patch.object(D.sp,'run') as run:
            with self.assertRaises(ValueError):D.launch(['hc','run','--','agent'])
            run.assert_not_called()
        with patch.dict(os.environ,{D.ENV:'{"bg":"#ffffff","fg":"#202020"}'}), patch.object(D.sp,'run',return_value=sp.CompletedProcess([],0,'{"id":1,"error":{"message":"unsupported"}}\n','')) as run:
            with self.assertRaises(RuntimeError):D.launch(['hc','run','--','agent'])
            self.assertEqual(run.call_count,1)
