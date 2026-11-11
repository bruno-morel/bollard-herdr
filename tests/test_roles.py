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
                module, "selected_role", return_value=("work", profile["work"])
            ):
                text = module.prompt(root, "sample", "work")
            self.assertIn("Engineering", text)
            self.assertIn("Prefer existing tooling", text)
            self.assertIn("One --follow-up is allowed", text)
            self.assertIn("Use this checkout and branch", text)

    def test_custom_profile_persistence_and_instructions_file(self):
        import json
        from repo_roles import select, selected

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf = root / ".bollard"
            conf.mkdir()
            (conf / "research.md").write_text("Cite your sources.")
            (conf / "roles.json").write_text(
                json.dumps(
                    {
                        "research": {
                            "base": "studio",
                            "label": "Research",
                            "instructions_file": "research.md",
                            "handoff_to": ["work"],
                        }
                    }
                )
            )
            with patch.dict(os.environ, XDG_CONFIG_HOME=str(root / "config")):
                pref = root / "state/studio.agent"
                self.assertEqual(selected(root, pref, "studio")[0], "studio")
                select(root, pref, "studio", "research")
                identity, profile = selected(root, pref, "studio")
                self.assertEqual(identity, "research")
                self.assertIn("Cite your sources.", profile["instructions"])
                with self.assertRaises(RuntimeError):
                    select(root, pref, "work", "research")
                (conf / "roles.json").write_text(
                    '{"research":{"base":"studio","instructions_file":"../secret"}}'
                )
                with self.assertRaises(RuntimeError):
                    roles(root)

    def test_handoff_protects_destination_and_requires_implementation(self):
        import repo_role_handoff as H
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, XDG_CONFIG_HOME=tmp
        ):
            root = Path(tmp)
            source = {
                "address": "t1",
                "state": "live",
                "labels": {"repo-tools.role": "studio", "repo-tools.stream": "sample"},
            }
            api = SimpleNamespace(packet=lambda *_: root)
            with self.assertRaisesRegex(RuntimeError, "Build the implementation"):
                H.prepare(api, root, "sample", source, "work", [source])
            (root / "implementation.md").write_text("Implement the agreed scope")
            target = {
                "address": "t2",
                "state": "live",
                "labels": {"repo-tools.role": "work", "repo-tools.stream": "sample"},
            }
            with self.assertRaisesRegex(RuntimeError, "already open"):
                H.prepare(api, root, "sample", source, "work", [source, target])
            job = H.prepare(api, root, "sample", source, "work", [source])
            H.validate(root, job)
            self.assertEqual(
                H.notes("sample", job), "docs/handoffs/sample/roles/studio.md"
            )
            with patch.object(
                H.profiles, "roles", return_value={"work": {"label": "Changed"}}
            ):
                with self.assertRaisesRegex(RuntimeError, "configuration changed"):
                    H.validate(root, job)
