"""Structured provider results fail closed without paid calls."""

import json
from pathlib import Path
import tempfile
import unittest
import repo_agents as A


class Agents(unittest.TestCase):
    def test_all_providers_require_a_structured_object(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "schema.json").write_text("{}")
            for name in A.AGENTS:
                argv = A.structured_argv(name, name, root, root, "Inspect")
                self.assertNotIn("--force", argv)
                self.assertNotIn("--yolo", argv)
                result = {"summary": "Evidence"}
                envelope = (
                    result
                    if name == "codex"
                    else {
                        "subtype": "success",
                        "structured_output": result,
                        "result": json.dumps(result),
                    }
                )
                path = root / ("result.json" if name == "codex" else "agent.log")
                path.write_text(json.dumps(envelope))
                self.assertEqual(A.structured_result(name, root), result)
                path.write_text("null")
                with self.assertRaises(RuntimeError):
                    A.structured_result(name, root)
                path.write_text(json.dumps({"is_error": True, "result": "{}"}))
                if name != "codex":
                    with self.assertRaises(RuntimeError):
                        A.structured_result(name, root)
