"""Exercise menu dispatch without launching terminals, agents or tests."""

import contextlib
import io
import unittest
from unittest.mock import Mock, patch
import repo_flow_menu as M


class FlowMenu(unittest.TestCase):
    def drive(self, answers, role="work", dispatch=None):
        dispatch = dispatch or Mock()
        output = io.StringIO()
        with patch.object(M.sys.stdin, "isatty", return_value=True), patch(
            "builtins.input", side_effect=answers
        ), patch.object(M.sp, "run") as run, contextlib.redirect_stdout(output):
            M.run_menu(role, dispatch)
        return dispatch, run, output.getvalue()

    def test_noninteractive_menu_refuses_without_side_effects(self):
        dispatch = Mock()
        with patch.object(M.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "subcommand"):
                M.run_menu("work", dispatch)
        dispatch.assert_not_called()

    def test_open_uses_picker_and_does_not_dispatch_a_second_launch(self):
        dispatch, run, _ = self.drive(["1", "2", "q"])
        dispatch.assert_not_called()
        self.assertEqual(
            [call.args[0][-1] for call in run.call_args_list], ["studio", "work"]
        )
        self.assertTrue(
            all(
                call.args[0][0].endswith("/repo-workflow")
                for call in run.call_args_list
            )
        )

    def test_research_and_code_helpers_preserve_studio_role_and_scope(self):
        dispatch, run, _ = self.drive(
            ["5", "demo", "Inspect logs", "6", "demo", "Fix one widget", "q"], "studio"
        )
        run.assert_not_called()
        args = [call.args[0] for call in dispatch.call_args_list]
        self.assertEqual([a[a.index("--kind") + 1] for a in args], ["research", "code"])
        self.assertTrue(all(a[a.index("--role") + 1] == "studio" for a in args))
        self.assertEqual(args[1][-1], "Fix one widget")

    def test_pane_helper_preview_requires_explicit_yes_to_launch(self):
        for answer, expected_calls in [("", 1), ("n", 1), ("y", 2)]:
            with self.subTest(answer=answer):
                dispatch, run, _ = self.drive(
                    ["h", "demo", "1", "/context.json", "", "", answer, "q"]
                )
                self.assertEqual(dispatch.call_count, expected_calls)
                self.assertEqual(dispatch.call_args_list[0].args[0][-1], "--preview")
                if expected_calls == 2:
                    self.assertNotIn("--preview", dispatch.call_args_list[1].args[0])
                run.assert_not_called()

    def test_failed_preview_reports_error_without_launch_or_confirmation(self):
        dispatch = Mock(side_effect=RuntimeError("Wrong checkout"))
        _, run, output = self.drive(
            ["h", "demo", "1", "/context.json", "", "", "q"], dispatch=dispatch
        )
        dispatch.assert_called_once()
        run.assert_not_called()
        self.assertIn("Wrong checkout", output)

    def test_first_tests_pass_child_identity_and_use_project_controller(self):
        dispatch, run, _ = self.drive(["t", "demo", "first", "t42", "cursor", "q"])
        dispatch.assert_not_called()
        argv = run.call_args.args[0]
        self.assertTrue(argv[0].endswith("/work"))
        self.assertEqual(
            argv[1:],
            [
                "tests",
                "first",
                "demo",
                "--target",
                "t42",
                "--agent",
                "cursor",
                "--json",
            ],
        )

    def test_invalid_choices_do_not_start_anything(self):
        dispatch, run, _ = self.drive(
            ["bad", "h", "demo", "0", "t", "demo", "nonsense", "q"]
        )
        dispatch.assert_not_called()
        run.assert_not_called()
