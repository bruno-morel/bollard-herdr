import unittest
from repo_test_progress import view

class Progress(unittest.TestCase):
    def data(self,**kw):
        s=dict(state='stale',token='old',checks=[{}, {}, {}],results=[{'exit_code':0},{'exit_code':1}],repair=dict(state='sent',run='old'))
        s.update(kw);return s
    def test_sent_is_not_a_fix(self):
        v=view(self.data());self.assertEqual(v['label'],'Repair requested');self.assertTrue(v['historical'])
    def test_explicit_phase_does_not_change_results(self):
        v=view(self.data(),dict(run='old',phase='fixing'))
        self.assertEqual((v['label'],v['passed'],v['failed'],v['unrun']),('Fixing',1,1,1))
    def test_real_runner_overrides_reported_stage(self):
        v=view(self.data(state='running',token='new'),dict(run='old',phase='fixing'))
        self.assertEqual(v['phase'],'rerunning');self.assertFalse(v['historical'])
    def test_only_fresh_results_are_verified(self):
        for state,phase in [('passed','verified'),('stale','stale'),('failed','failed'),('incomplete','incomplete')]:
            v=view(self.data(state=state,token='new'),dict(run='old',phase='fixing'))
            self.assertEqual(v['phase'],phase)
    def test_old_reports_do_not_override_new_request(self):
        v=view(self.data(),dict(run='unrelated',phase='fixing'))
        self.assertEqual(v['label'],'Repair requested')
    def test_existing_agent_has_honest_fallback_without_guessing_fix(self):
        s=self.data();s['repair']['lead_state']='working'
        self.assertEqual(view(s)['label'],'Agent working · stage not reported')
        s['repair']['lead_state']='done'
        self.assertEqual(view(s)['phase'],'awaiting-tests')
        self.assertNotEqual(view(s)['tone'],'success')
    def test_timeout_is_incomplete_not_passed(self):
        v=view(self.data(results=[{'exit_code':-1}]))
        self.assertEqual((v['passed'],v['failed'],v['incomplete']),(0,0,1))

    def test_active_check_is_running_not_unrun(self):
        v=view(self.data(state='running',current='active',results=[]))
        self.assertEqual((v['running'],v['unrun']),(1,2))
