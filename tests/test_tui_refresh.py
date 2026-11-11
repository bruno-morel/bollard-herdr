"""Deterministic background-request races without curses, SSH or agents."""
from concurrent.futures import Future
import unittest
from unittest.mock import Mock, patch

from repo_tui_panel import Panel


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.panel = object.__new__(Panel)
        p = self.panel
        p.address = 'host/t1'
        p.row = {'address': p.address}
        p.pending = {}
        p.cache = {}
        p.errors = {}
        p.last = {}
        p.pool = Mock()
        p.markdown_future = None
        p.preview_request = None
        p.route_pending = None
        p.checkpoint_notice = None
        p.message = ''

    def submit(self, key='lead', running=True, **kwargs):
        future = Future()
        if running:
            future.set_running_or_notify_cancel()
        self.panel.pool.submit.return_value = future
        self.panel.fetch(key, lambda: None, **kwargs)
        return future

    def test_switch_away_and_back_cannot_accept_previous_result(self):
        old = self.submit()
        self.panel.select_stream({'address': 'host/t2'})
        self.panel.select_stream({'address': 'host/t1'})
        new = self.submit()
        old.set_result({'message': 'obsolete'})
        self.panel.collect()
        self.assertEqual(self.panel.cache, {})
        self.assertIn('lead', self.panel.pending)
        new.set_result({'message': 'current'})
        self.panel.collect()
        self.assertEqual(self.panel.cache['lead'], {'message': 'current'})

    def test_queued_requests_are_cancelled_without_cancelling_running_agent(self):
        queued = self.submit(running=False)
        markdown = Future()
        self.panel.markdown_future = markdown
        self.panel.select_stream({'address': 'host/t2'})
        self.assertTrue(queued.cancelled())
        self.assertTrue(markdown.cancelled())
        self.assertEqual(self.panel.pending, {})
        self.assertIsNone(self.panel.markdown_future)
        self.assertEqual(self.panel.pool.method_calls[0][0], 'submit')

    def test_same_stream_updates_metadata_without_losing_pending_work(self):
        future = self.submit()
        row = {'address': 'host/t1', 'labels': {'repo-tools.agent': 'cursor'}}
        self.panel.select_stream(row)
        self.assertEqual(self.panel.row, row)
        self.assertIs(self.panel.pending['lead'][1], future)
        self.assertFalse(future.cancelled())

    def test_selection_clears_old_document_and_error_state(self):
        p = self.panel
        p.cache = {'files': {'files': ['old']}}
        p.errors = {'review': 'old failure'}
        p.preview_request = 'preview:old'
        p.preview = {'text': 'private to previous stream'}
        p.route_ack = ('host/t1', 'request', 'docs')
        p.doc_history = ['old.md']
        p.message = 'Previous checkpoint failed'
        p.select_stream({})
        self.assertEqual((p.cache, p.errors, p.doc_history, p.message), ({}, {}, [], ''))
        self.assertIsNone(p.preview)
        self.assertIsNone(p.preview_request)
        self.assertIsNone(p.route_ack)

    def test_force_does_not_duplicate_inflight_request(self):
        self.submit()
        self.panel.fetch('lead', lambda: None, force=True)
        self.assertEqual(self.panel.pool.submit.call_count, 1)

    def test_first_request_is_not_throttled_by_machine_uptime(self):
        with patch('repo_tui_panel.time.monotonic', return_value=1):
            future = self.submit(period=30)
        self.assertIn('lead', self.panel.pending)
        future.set_result({})
        self.panel.collect()
        with patch('repo_tui_panel.time.monotonic', return_value=2):
            self.panel.fetch('lead', lambda: None, period=30)
        self.assertEqual(self.panel.pool.submit.call_count, 1)

    def test_failed_refresh_retains_error_until_success(self):
        p = self.panel
        p.cache['lead'] = {'old': True}
        future = self.submit()
        future.set_exception(RuntimeError('connection lost'))
        p.collect()
        self.assertEqual(p.errors['lead'], 'connection lost')
        self.assertEqual(p.cache['lead'], {'old': True})
        future = self.submit(force=True)
        future.set_result({'new': True})
        p.collect()
        self.assertNotIn('lead', p.errors)
        self.assertEqual(p.cache['lead'], {'new': True})
