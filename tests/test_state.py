"""Exercise replacement failures without touching installed runtime state."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repo_state import write_json


class StateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'state.json'
        self.path.write_text('{"old": true}')

    def assert_previous_intact(self):
        self.assertEqual(json.loads(self.path.read_text()), {'old': True})
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_serialization_failure_keeps_previous_and_removes_partial_file(self):
        with self.assertRaises(TypeError):
            write_json(self.path, {'written_first': 1, 'invalid': object()})
        self.assert_previous_intact()

    def test_replace_failure_keeps_previous_and_cleans_up(self):
        with patch('repo_state.os.replace', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                write_json(self.path, {'new': True})
        self.assert_previous_intact()

    def test_private_complete_file_exists_before_replace(self):
        import os
        replace = os.replace

        def inspect(source, target):
            self.assertEqual(source.parent, self.root)
            self.assertEqual(source.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(source.read_text()), {'name': 'café'})
            self.assertEqual(json.loads(target.read_text()), {'old': True})
            replace(source, target)

        with patch('repo_state.os.replace', side_effect=inspect):
            write_json(self.path, {'name': 'café'}, indent=2)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_parallel_replacements_are_whole_records(self):
        records = [{'writer': i, 'payload': str(i) * 10000} for i in range(20)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda data: write_json(self.path, data), records))
        self.assertIn(json.loads(self.path.read_text()), records)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_missing_parent_is_not_silently_created(self):
        with self.assertRaises(FileNotFoundError):
            write_json(self.root / 'missing' / 'state.json', {})
        self.assertFalse((self.root / 'missing').exists())

    def test_replace_does_not_write_through_destination_symlink(self):
        target = self.root / 'other.json'
        target.write_text('{"untouched": true}')
        self.path.unlink()
        self.path.symlink_to(target)
        write_json(self.path, {'new': True})
        self.assertFalse(self.path.is_symlink())
        self.assertEqual(json.loads(target.read_text()), {'untouched': True})
        self.assertEqual(json.loads(self.path.read_text()), {'new': True})
