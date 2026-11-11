"""Viewing a panel builds read-only requests, not agent or test launches."""
import unittest
from unittest.mock import Mock

from repo_tui_queries import queries


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.row = {'address': 'host/t2', 'labels': {'repo-tools.stream': 'demo'}}

    def requests(self, tab, **options):
        result = queries(self.backend, self.row, tab, **options)
        self.assertEqual(self.backend.mock_calls, [])
        return {key: (fn, period) for key, fn, period in result}

    def test_review_reads_evidence_without_launch(self):
        requests = self.requests('review', panel=True)
        self.assertEqual(set(requests), {'lead', 'checkpoint', 'review', 'completion'})
        for fn, period in requests.values():
            fn()
        self.backend.work.assert_any_call(self.row, 'review', 'demo', '--status', '--json')
        self.backend.work.assert_any_call(self.row, 'complete', 'demo', '--status', '--json')
        self.backend.call.assert_called_once_with(self.row, 'repo-new-conversation.py', ['demo', '--status'])
        self.assertEqual(requests['completion'][1], 15)

    def test_tests_only_reads_status(self):
        requests = self.requests('tests')
        requests['tests'][0]()
        self.backend.work.assert_called_once_with(self.row, 'tests', 'status', 'demo', '--json')

    def test_usage_metadata_requested_once_and_no_auth_or_review_launch(self):
        requests = self.requests('usage')
        self.assertEqual(set(requests), {'lead', 'usage', 'review', 'metadata'})
        for fn, _ in requests.values():
            fn()
        self.backend.call.assert_any_call(self.row, 'repo-provider.py', ['status'])
        self.backend.call.assert_any_call(self.row, 'repo-panel.py', ['metadata', 't2'])
        self.assertEqual(self.backend.call.call_count, 2)
        self.backend.work.assert_called_once_with(self.row, 'review', 'demo', '--status', '--json')

    def test_frozen_logs_do_not_refresh_but_lead_stays_visible(self):
        self.assertEqual(set(self.requests('docker', frozen=True)), {'lead'})

    def test_logs_start_follower_only_for_active_stack(self):
        requests = self.requests('docker')
        for state in ('unprepared', 'empty', 'stopped'):
            self.backend.work.return_value = {'state': state}
            self.assertEqual(requests['docker'][0](), {'state': state})
        self.backend.call.assert_not_called()
        self.backend.work.return_value = {'state': 'active', 'project': 'ours'}
        self.backend.call.return_value = {'state': 'following', 'logs': 'hello'}
        self.assertEqual(requests['docker'][0](), {'state': 'following', 'project': 'ours', 'logs': 'hello'})
        self.backend.call.assert_called_once_with(self.row, 'repo-logfeed.py', ['poll', 'demo'])

    def test_lazy_requests_keep_selected_stream_address(self):
        requests = self.requests('files', attached=True)
        original = dict(self.row)
        self.row['address'] = 'other/t9'
        requests['lead'][0]()
        requests['files'][0]()
        self.backend.hc.assert_called_once_with('get', 'host/t2')
        self.backend.data.assert_called_once_with(original, 'files')
        self.assertEqual(requests['lead'][1], 1)

    def test_information_views_use_expected_sources(self):
        for tab, key in [('docs', 'docs'), ('git', 'git'), ('git-info', 'git'), ('agents', 'agents'), ('questions', 'agents'), ('context', 'metadata'), ('services', 'services')]:
            with self.subTest(tab=tab):
                requests = self.requests(tab)
                self.assertIn(key, requests)
                requests[key][0]()
                self.assertEqual(len(self.backend.mock_calls), 1)
                self.backend.reset_mock()
