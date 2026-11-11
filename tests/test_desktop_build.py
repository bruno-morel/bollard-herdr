"""Keep the gallery package usable without making generated files editable sources."""
import json
from pathlib import Path
import tempfile
import unittest

import desktop_build as B


class SharedDesktopPackage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'desktop/shared').mkdir(parents=True)
        self.source = self.root / 'desktop/shared/state.js'
        self.source.write_text('export const value = 1;\n')
        self.manifest = self.root / 'desktop/shared.json'
        self.manifest.write_text(json.dumps({'state.js': ['one/state.js', 'two/state.js']}))
        for name in ('one', 'two'):
            mod = self.root / 'herdr/mods' / name
            mod.mkdir(parents=True)
            (mod / 'mod.json').write_text('{}')

    def test_builds_identical_self_contained_helpers_and_is_idempotent(self):
        self.assertEqual(B.build(self.root), 2)
        one = self.root / 'herdr/mods/one/state.js'
        two = self.root / 'herdr/mods/two/state.js'
        self.assertEqual(one.read_bytes(), two.read_bytes())
        self.assertTrue(one.read_bytes().endswith(self.source.read_bytes()))
        before = one.stat().st_mtime_ns
        B.build(self.root)
        self.assertEqual(before, one.stat().st_mtime_ns)

    def test_check_refuses_stale_generated_file_without_repairing_it(self):
        B.build(self.root)
        target = self.root / 'herdr/mods/one/state.js'
        target.write_text('// edited by hand\n')
        with self.assertRaisesRegex(ValueError, 'generated helpers differ'):
            B.check(self.root)
        self.assertEqual(target.read_text(), '// edited by hand\n')

    def test_source_change_requires_regeneration(self):
        B.build(self.root)
        self.source.write_text('export const value = 2;\n')
        with self.assertRaises(ValueError):
            B.check(self.root)
        B.build(self.root)
        B.check(self.root)

    def test_invalid_manifest_is_rejected_before_any_write(self):
        for destination in ('../../escape.js', '/escape.js', 'unknown/file.js'):
            with self.subTest(destination=destination):
                self.manifest.write_text(json.dumps({'state.js': ['one/state.js', destination]}))
                with self.assertRaises(ValueError):
                    B.build(self.root)
                self.assertFalse((self.root / 'herdr/mods/one/state.js').exists())

    def test_rejects_duplicate_and_orphan_outputs(self):
        self.manifest.write_text(json.dumps({'state.js': ['one/state.js', 'one/state.js']}))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            B.build(self.root)
        self.manifest.write_text(json.dumps({'state.js': ['one/state.js']}))
        orphan = self.root / 'herdr/mods/two/state.js'
        orphan.write_bytes(B.MARKER + b'orphan\n')
        with self.assertRaisesRegex(ValueError, 'Orphan'):
            B.build(self.root)

    def test_rejects_unused_shared_source(self):
        (self.source.parent / 'unused.js').write_text('// old helper')
        with self.assertRaisesRegex(ValueError, 'manifest differs'):
            B.build(self.root)

    def test_rejects_symlink_destination(self):
        elsewhere = self.root / 'elsewhere.js'
        elsewhere.write_text('keep me')
        (self.root / 'herdr/mods/one/state.js').symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            B.build(self.root)
        self.assertEqual(elsewhere.read_text(), 'keep me')
