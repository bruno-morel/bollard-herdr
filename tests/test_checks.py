import copy
import unittest
from repo_checks import validate_commands


class CheckDefinitions(unittest.TestCase):
    def setUp(self):
        self.check = dict(id="unit", kind="unit", argv=["npm", "test"])

    def test_defaults_and_argument_boundaries_are_preserved(self):
        checks = [
            dict(self.check, argv=["runner", "path with spaces", "literal; value"])
        ]
        before = copy.deepcopy(checks)
        self.assertEqual(validate_commands(checks), {"unit"})
        self.assertEqual(checks, before)

    def test_rejects_invalid_commands_and_escape_paths(self):
        for field, values in {
            "id": ["", None, "UPPER"],
            "kind": ["unknown", None],
            "argv": [[], None, "npm test", ["cmd", False], ["cmd", "x\0y"]],
            "cwd": ["", None, "../elsewhere", "/tmp", "bad\0path"],
            "timeout": [True, 0, 301, 1.5],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(
                    RuntimeError
                ):
                    validate_commands([dict(self.check, **{field: value})])

    def test_duplicate_ids_and_total_budget_are_bounded(self):
        for checks in (
            [],
            [self.check, self.check],
            [dict(self.check, id="test-" + str(i), timeout=300) for i in range(5)],
            [dict(self.check, id="test-" + str(i)) for i in range(9)],
        ):
            with self.assertRaises(RuntimeError):
                validate_commands(checks)
