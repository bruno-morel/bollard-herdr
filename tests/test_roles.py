import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repo_roles import roles


class RoleTests(unittest.TestCase):
    def test_precedence_and_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            (config / "bollard").mkdir(parents=True)
            (config / "bollard/roles.json").write_text(
                '{"studio":{"label":"Planning","instructions":"Keep evidence"}}'
            )
            (root / ".bollard").mkdir()
            (root / ".bollard/roles.json").write_text(
                '{"studio":{"label":"Marketing"}}'
            )
            with patch.dict(os.environ, XDG_CONFIG_HOME=str(config)):
                value = roles(root)
                self.assertEqual(value["studio"]["label"], "Marketing")
                self.assertEqual(value["studio"]["instructions"], "Keep evidence")
                self.assertEqual(value["work"]["label"], "Work")

    def test_invalid_role_and_fields_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".bollard").mkdir()
            with patch.dict(os.environ, XDG_CONFIG_HOME=str(root / "config")):
                for content in (
                    '{"deploy":{}}',
                    '{"work":{"docker":false}}',
                    '{"studio":{"label":""}}',
                    "[]",
                ):
                    (root / ".bollard/roles.json").write_text(content)
                    with self.assertRaisesRegex(
                        RuntimeError, "Invalid role configuration"
                    ):
                        roles(root)

    def test_custom_prompt_keeps_work_policy(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "role_agent", Path(__file__).parent / "repo-agent.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = {
                "work": {
                    "label": "Engineering",
                    "instructions": "Prefer existing tooling",
                }
            }
            with patch.object(
                module, "preferences", return_value=root / "work.agent"
            ), patch.object(module, "packet", return_value=root), patch.object(
                module, "roles", return_value=profile
            ):
                text = module.prompt(root, "sample", "work")
            self.assertIn("Engineering", text)
            self.assertIn("Prefer existing tooling", text)
            self.assertIn("One --follow-up is allowed", text)
            self.assertIn("Use this checkout and branch", text)
