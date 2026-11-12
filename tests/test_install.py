import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "installer", Path(__file__).with_name("install.py")
)
I = importlib.util.module_from_spec(spec)
spec.loader.exec_module(I)


class Installer(unittest.TestCase):
    def setUp(self):
        self.dependencies = patch.object(I, "check_dependencies", return_value=True)
        self.dependencies.start()
        self.addCleanup(self.dependencies.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.home = self.root / "home"
        (self.source / "bin").mkdir(parents=True)
        self.home.mkdir()
        (self.source / "desktop/shared").mkdir(parents=True)
        (self.source / "desktop/shared.json").write_text("{}")
        for name in (
            "repo_operations.py",
            "repo_tui_panel.py",
            "repo-workflow",
            "repo-streams.py",
        ):
            (self.source / "bin" / name).write_text("pass\n")
        (self.source / "baseline.json").write_text("{}")
        (self.source / "tui").mkdir()
        (self.source / "tui/studio-work-v2.toml").write_text('shell = "@HOME@/bin/shell"\n')

    def tearDown(self):
        self.temp.cleanup()

    def run_install(self, flag):
        with patch.object(I, "SOURCE", self.source), patch.object(
            Path, "home", return_value=self.home
        ), patch("sys.argv", ["install.py", "laptop", flag]), patch.dict(
            "os.environ", {"XDG_STATE_HOME": str(self.home / "state")}
        ), contextlib.redirect_stdout(
            io.StringIO()
        ):
            I.main()

    def test_stale_desktop_package_blocks_install_before_any_writes(self):
        (self.source / "desktop/shared/state.js").write_text("export const v = 2;\n")
        (self.source / "desktop/shared.json").write_text(
            json.dumps({"state.js": ["example/state.js"]})
        )
        mod = self.source / "herdr/mods/example"
        mod.mkdir(parents=True)
        (mod / "mod.json").write_text("{}")
        (mod / "state.js").write_text("export const v = 1;\n")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_install("--apply")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_dependencies_block_apply_before_writes(self):
        with patch.object(I, "check_dependencies", return_value=False):
            with self.assertRaisesRegex(SystemExit, "prerequisites"):
                self.run_install("--apply")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_dependency_check_never_installs(self):
        self.run_install("--check-deps")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_desktop_and_tui_have_separate_interface_targets(self):
        mod = self.source / "herdr/mods/example"
        mod.mkdir(parents=True)
        (mod / "main.js").write_text("// source")
        with patch.object(I, "SOURCE", self.source):
            desktop = [str(dst) for _, dst in I.targets("desktop", self.home)]
            tui = [str(dst) for _, dst in I.targets("tui", self.home)]
        self.assertTrue(any("herdr-app/mods" in x for x in desktop))
        self.assertFalse(any("studio-work-v2.toml" in x for x in desktop))
        self.assertTrue(any("studio-work-v2.toml" in x for x in tui))
        self.assertFalse(any("herdr-app/mods" in x for x in tui))

    def test_screen_lock_files_are_not_installation_targets(self):
        screens = self.home / ".config/herdr-app/screens"
        screens.mkdir(parents=True)
        (screens / "example.lock").write_text("")
        mod = self.source / "herdr/mods/example"
        mod.mkdir(parents=True)
        (mod / "main.js").write_text("// source")
        with patch.object(I, "SOURCE", self.source):
            targets = list(I.targets("laptop", self.home))
        self.assertFalse(any("example.lock" in str(dst) for _, dst in targets))

    def test_existing_layout_pins_are_preserved(self):
        source = self.source / "herdr/layouts"
        source.mkdir(parents=True)
        (source / "layout.json").write_text("{}")
        target = self.home / ".config/herdr-app/layouts"
        target.mkdir(parents=True)
        (target / "layout.json").write_text('{"private": true}')
        self.run_install("--apply")
        self.assertEqual((target / "layout.json").read_text(), '{"private": true}')

    def test_tui_home_is_rendered_for_installation(self):
        self.run_install("--apply")
        data = (self.home / ".config/herdr/studio-work-v2.toml").read_text()
        self.assertIn(str(self.home), data)
        self.assertNotIn("@HOME@", data)

    def test_python_cache_is_not_installed(self):
        cache = self.source / "bin/__pycache__"
        cache.mkdir()
        (cache / "module.cpython-311.pyc").write_bytes(b"cache")
        self.run_install("--apply")
        self.assertFalse((self.home / ".local/bin/__pycache__").exists())

    def test_preview_makes_no_files(self):
        with patch.object(I, "SOURCE", self.source), patch.object(
            Path, "home", return_value=self.home
        ), patch("sys.argv", ["install.py", "laptop"]), patch.dict(
            "os.environ", {"XDG_STATE_HOME": str(self.home / "state")}
        ), contextlib.redirect_stdout(io.StringIO()):
            I.main()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_failed_update_restores_previous_files_and_manifest(self):
        self.run_install("--apply")
        installed = self.home / ".local/bin"
        before = {p.name: p.read_bytes() for p in installed.iterdir()}
        manifest = self.home / "state/repo-tools/source-install.json"
        old_manifest = manifest.read_bytes()
        for p in (self.source / "bin").iterdir():
            p.write_text("changed = True\n")
        write = I.atomic_write
        calls = 0

        def fail_second(path, data, mode):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk failure")
            return write(path, data, mode)

        with patch.object(I, "atomic_write", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.run_install("--apply")
        self.assertEqual(before, {p.name: p.read_bytes() for p in installed.iterdir()})
        self.assertEqual(old_manifest, manifest.read_bytes())

    def test_apply_then_verify(self):
        self.run_install("--apply")
        self.run_install("--verify")
        self.assertTrue((self.home / "state/repo-tools/source-install.json").exists())

    def test_drift_refuses_without_overwriting(self):
        self.run_install("--apply")
        path = self.home / ".local/bin/repo-streams.py"
        path.write_text("# user edit\n")
        with self.assertRaisesRegex(SystemExit, "reconcile"):
            self.run_install("--apply")
        self.assertEqual(path.read_text(), "# user edit\n")

    def test_new_managed_window_accepts_only_verified_primary_copies(self):
        mod = self.source / "herdr/mods/example"
        mod.mkdir(parents=True)
        (mod / "main.js").write_text("// old")
        self.run_install("--apply")
        app = self.home / ".config/herdr-app"
        window = app / "screens/new"
        (window / "mods/example").mkdir(parents=True)
        target = window / "mods/example/main.js"
        target.write_text("// private edit")
        (window / "repo-window.json").write_text(json.dumps({"origin":str(app)}))
        (mod / "main.js").write_text("// new")
        with self.assertRaisesRegex(SystemExit, "reconcile"):
            self.run_install("--apply")
        self.assertEqual(target.read_text(), "// private edit")
        target.write_text("// old")
        self.run_install("--apply")
        self.assertEqual(target.read_text(), "// new")

    def test_known_installed_version_can_update(self):
        self.run_install("--apply")
        (self.source / "bin/repo-streams.py").write_text("value = 2\n")
        self.run_install("--apply")
        self.run_install("--verify")


if __name__ == "__main__":
    unittest.main()
