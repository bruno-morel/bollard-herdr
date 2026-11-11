import importlib.util, os, subprocess as sp, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "streams", Path(__file__).with_name("repo-streams.py")
)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


class Retry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.work = self.bin / "work"
        self.work.write_text("#!/bin/sh\nexit 1\n")
        self.work.chmod(0o755)
        for a in [
            ("init", "-q", "-b", "main"),
            ("config", "user.email", "test@example.com"),
            ("config", "user.name", "Test"),
            ("commit", "--allow-empty", "-qm", "base"),
        ]:
            sp.run(["git", "-C", str(self.root), *a], check=True)
        self.env = patch.dict(os.environ, XDG_STATE_HOME=str(self.base / "state"))
        self.env.start()
        self.bind = patch.object(S, "BIN", self.bin)
        self.bind.start()

    def tearDown(self):
        self.bind.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_retry_preserves_checkout_and_changes(self):
        with self.assertRaises(RuntimeError):
            S.prepare(self.root, "new", "sample", ref="refs/heads/main")
        tree = Path(str(self.root) + "-worktrees") / "sample"
        (tree / "keep.txt").write_text("unfinished")
        self.work.write_text("#!/bin/sh\nexit 0\n")
        out = S.prepare(self.root, "new", "sample", ref="refs/heads/main", retry=True)
        self.assertTrue(os.path.samefile(out["checkout"], tree))
        self.assertEqual((tree / "keep.txt").read_text(), "unfinished")
        self.assertEqual(len(S.catalog(self.root)["trees"]), 2)

    def test_retry_refuses_other_destination(self):
        with self.assertRaises(RuntimeError):
            S.prepare(self.root, "new", "sample", ref="refs/heads/main")
        with self.assertRaisesRegex(RuntimeError, "differs"):
            S.prepare(
                self.root,
                "new",
                "sample",
                folder="different",
                ref="refs/heads/main",
                retry=True,
            )

    def test_normal_creation_still_refuses_duplicate(self):
        with self.assertRaises(RuntimeError):
            S.prepare(self.root, "new", "sample", ref="refs/heads/main")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            S.prepare(self.root, "new", "sample", ref="refs/heads/main")


if __name__ == "__main__":
    unittest.main()
