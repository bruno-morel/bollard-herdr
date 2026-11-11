"""Publication checks cover the whole checkout, not only deployed scripts."""

from pathlib import Path
import subprocess as sp
import tempfile
import unittest
import check_sources as C


class SourceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sp.run(["git", "init", "-q", str(self.root)], check=True)

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_includes_root_docs_tests_and_new_files_but_not_ignored_artifacts(self):
        self.put(".gitignore", "__pycache__/\n*.d.ts\nlocal/\n")
        names = ["install.py", "docs/setup.md", "tests/test_new.py", "bin/new tool"]
        for name in names:
            self.put(name, "pass\n")
        for name in [
            "bin/__pycache__/cached.pyc",
            "herdr/mods/sdk.d.ts",
            "local/config",
        ]:
            self.put(name, "ignored")
        sp.run(["git", "-C", str(self.root), "add", "install.py"], check=True)
        actual = {str(p.relative_to(self.root)) for p in C.sources(self.root)}
        self.assertEqual(actual, set(names + [".gitignore"]))

    def test_tracked_ignored_files_are_still_scanned(self):
        self.put("local/config", "tracked before ignoring")
        sp.run(["git", "-C", str(self.root), "add", "local/config"], check=True)
        self.put(".gitignore", "local/\n")
        self.assertIn(self.root / "local/config", list(C.sources(self.root)))

    def test_source_symlinks_are_rejected(self):
        self.put("file.py", "pass\n")
        (self.root / "linked.py").symlink_to("file.py")
        with self.assertRaisesRegex(ValueError, "symlink"):
            list(C.sources(self.root))

    def test_private_data_in_documentation_is_rejected_without_echoing_it(self):
        secret = "gh" + "p_" + "a" * 36
        p = self.put("docs/setup.md", secret)
        with self.assertRaises(ValueError) as caught:
            C.check(p)
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("docs/setup.md", str(caught.exception))

    def test_python_and_json_validation_include_root_files(self):
        with self.assertRaises(SyntaxError):
            C.check(self.put("install.py", "def broken(:\n"))
        with self.assertRaises(ValueError):
            C.check(self.put("config.json", "{"))
        C.check(self.put("install.py", "pass\n"))
        C.check(self.put("config.json", "{}"))
