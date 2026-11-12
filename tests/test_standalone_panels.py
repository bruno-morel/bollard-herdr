import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess as sp
import tempfile
import unittest
from unittest.mock import patch
import repo_file_io as F
import install_mods as I

spec = importlib.util.spec_from_file_location(
    "standalone_panel", Path(__file__).with_name("bollard-panel.py")
)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


class StandaloneFiles(unittest.TestCase):
    def test_save_preserves_mode_and_rejects_stale_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "notes.md"
            file.write_text("# Before")
            file.chmod(0o640)
            with patch.object(F, "root", return_value=root):
                doc = F.file_data("notes.md")
                F.save("notes.md", doc["digest"], "# After")
                self.assertEqual(file.stat().st_mode & 0o777, 0o640)
                with self.assertRaisesRegex(RuntimeError, "changed on disk"):
                    F.save("notes.md", doc["digest"], "Lost update")
                self.assertEqual(file.read_text(), "# After")

    def test_paths_binary_and_large_files_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "link").symlink_to("/tmp")
            (root / "binary").write_bytes(b"x\0y")
            (root / "large").write_text("x" * 100001)
            with patch.object(F, "root", return_value=root):
                for path in (
                    "../outside",
                    "/etc/passwd",
                    ".git/config",
                    "link/file",
                    "binary",
                    "large",
                ):
                    with self.subTest(path=path), self.assertRaises(RuntimeError):
                        F.file_data(path)


class StandaloneDocker(unittest.TestCase):
    def test_no_compose_is_empty_not_an_unrelated_parent_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            (parent / "compose.yaml").write_text("services: {}")
            root = parent / "child"
            root.mkdir()
            with patch.object(P, "compose_root", return_value=root), patch.object(
                P, "execute"
            ) as call:
                self.assertEqual(P.docker("docker-status")["state"], "unprepared")
                with self.assertRaisesRegex(RuntimeError, "Add a compose"):
                    P.docker("docker-start")
                call.assert_not_called()

    def test_project_scope_override_and_ndjson_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compose.yaml").write_text("services: {}")
            (root / "compose.override.yaml").write_text("services: {}")
            args = P.compose_args(root)
            self.assertEqual(args.count("-f"), 2)
            with patch.object(P, "compose_root", return_value=root), patch.object(
                P,
                "execute",
                return_value='{"Project":"example","State":"running"}\n{"Project":"example","State":"exited"}',
            ) as call:
                d = P.docker("docker-status")
                self.assertEqual(d["state"], "active")
                self.assertEqual(d["project"], "example")
                self.assertIn("--all", call.call_args.args[0])

    def test_compose_environment_never_inherits_another_stream(self):
        result = sp.CompletedProcess([], 0, "[]", "")
        with patch.dict(
            os.environ,
            COMPOSE_PROJECT_NAME="wrong",
            COMPOSE_FILE="wrong",
            COMPOSE_ENV_FILES="wrong",
        ), patch.object(P.sp, "run", return_value=result) as run:
            P.execute(["docker", "compose", "ps"], Path("/tmp"))
            self.assertNotIn("COMPOSE_PROJECT_NAME", run.call_args.kwargs["env"])
            self.assertNotIn("COMPOSE_FILE", run.call_args.kwargs["env"])

    def test_daemon_error_is_not_reported_as_no_containers(self):
        with patch.object(P, "compose_root", return_value=Path("/tmp")), patch.object(
            P, "compose_args", return_value=["docker", "compose"]
        ), patch.object(P, "execute", side_effect=RuntimeError("daemon unavailable")):
            with self.assertRaisesRegex(RuntimeError, "daemon unavailable"):
                P.docker("docker-status")


class StandaloneInstaller(unittest.TestCase):
    def test_install_does_not_touch_layouts_and_refuses_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            src = root / "src"
            mod = src / "packages/files/mods/bollard-files"
            mod.mkdir(parents=True)
            (mod / "main.js").write_text("export default {};")
            (mod / "jsconfig.json").write_text("{}")
            (mod / "gpui-kit.d.ts").write_text("// generated SDK")
            helpers = src / "packages/files/bin"
            helpers.mkdir()
            (helpers / "bollard-panel.py").write_text("#!/usr/bin/env python3\npass\n")
            layout = home / ".config/herdr-app/layout.json"
            layout.parent.mkdir(parents=True)
            layout.write_text("personal pins")
            with patch.object(I, "ROOT", src), patch.object(I, "build"), patch.dict(
                os.environ, XDG_STATE_HOME=str(home / "state")
            ), contextlib.redirect_stdout(io.StringIO()):
                I.install("files", home, apply=True)
                I.install("files", home, verify=True)
                self.assertEqual(layout.read_text(), "personal pins")
                self.assertFalse(
                    (
                        home / ".config/herdr-app/mods/bollard-files/jsconfig.json"
                    ).exists()
                )
                self.assertFalse(
                    (
                        home / ".config/herdr-app/mods/bollard-files/gpui-kit.d.ts"
                    ).exists()
                )
                target = home / ".config/herdr-app/mods/bollard-files/main.js"
                target.write_text("custom")
                with self.assertRaisesRegex(ValueError, "reconcile first"):
                    I.install("files", home, apply=True)
                self.assertEqual(target.read_text(), "custom")
                self.assertTrue(
                    all(
                        ".local/bin" in str(dest)
                        for _, dest in I.targets("files", home, True)
                    )
                )
