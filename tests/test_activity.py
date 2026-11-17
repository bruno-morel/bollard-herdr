import unittest
from repo_tui_present import activity

class ActivityTests(unittest.TestCase):
    def test_permission_and_timestamp(self):
        row = dict(state='live', created_ms=1, status_ms=60000, status=dict(state='blocked',kind='permission'))
        self.assertEqual(activity(row,120)['kind'], 'Permission needed')
        self.assertEqual(activity(row,120)['timing'], 'Last status 1m ago')
        row['status_ms'] = None
        self.assertEqual(activity(row,120)['timing'], 'Status time unavailable')
        row['status_ms'] = 999999
        self.assertEqual(activity(row,120)['timing'], 'Status time unavailable')

    def test_health_not_loop_detection(self):
        row = dict(state='live', status_ms=1, status='working')
        self.assertEqual(activity(row,999999)['health'], 'Status available')
        self.assertEqual(activity(row,999999,'offline')['health'], 'Status unavailable')
        self.assertEqual(activity(None,100)['health'], 'No conversation')
