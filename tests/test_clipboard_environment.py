import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


class ClipboardEnvironment(unittest.TestCase):
    def test_marker_only_for_codex_in_herdr(self):
        spec = importlib.util.spec_from_file_location(
            "clipboard_agent", Path(__file__).parent / "repo-agent.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in ("codex", "claude", "cursor"):
            for herdr in (False, True):
                source = {"PATH": "/test/bin"}
                if herdr:
                    source["HC_TERMINAL_ID"] = "test"
                with patch.dict(os.environ, source, clear=True):
                    env = module.agent_environment(name)
                    self.assertEqual(env.get("HERDR_ENV"),
                                     "1" if herdr and name == "codex" else None)
                    self.assertEqual(env["PATH"], "/test/bin")
                    self.assertNotIn("HERDR_ENV", os.environ)
                    self.assertNotIn("SSH_CONNECTION", env)
