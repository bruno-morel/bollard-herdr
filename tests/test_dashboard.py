import concurrent.futures
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import repo_tui_panel as P
import repo_tui_common as C

HERE = Path(__file__).resolve().parent


def module(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(HERE / file))
    spec = importlib.util.spec_from_loader(name, loader)
    value = importlib.util.module_from_spec(spec)
    loader.exec_module(value)
    return value


D = module("data", "repo-tui-data.py")


class RepositoryReads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dashboard repo ")
        self.old = Path.cwd()
        os.chdir(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        Path("docs").mkdir()
        Path("docs/brief.md").write_text("Initial\n")
        Path("app.py").write_text("original\n")
        Path(".gitignore").write_text("scratch/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Initial")

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], stderr=subprocess.STDOUT)

    def test_changed_docs_only_and_ignored_assets(self):
        Path("docs/brief.md").write_text("Edited\n")
        Path("docs/notes.txt").write_text("New")
        Path("scratch").mkdir()
        Path("scratch/large.md").write_text("ignored")
        Path("image.png").write_bytes(b"\0\0")
        rows = D.index("docs")["files"]
        self.assertEqual({r["path"] for r in rows}, {"docs/brief.md", "docs/notes.txt"})
        self.assertTrue(all(r["changed"] for r in rows))
        self.assertNotIn(
            "scratch/large.md", {r["path"] for r in D.index("files")["files"]}
        )

    def test_staged_and_unstaged_cancel_both_visible(self):
        Path("app.py").write_text("staged\n")
        self.git("add", "app.py")
        Path("app.py").write_text("original\n")
        out = D.preview("git", "app.py")["text"]
        self.assertIn("Staged\n", out)
        self.assertIn("Unstaged\n", out)
        self.assertIn("+staged", out)
        self.assertIn("-staged", out)

    def test_literal_pathspec_and_newlines(self):
        name = "docs/odd [x]\nfile.txt"
        Path(name).write_text("literal\n")
        self.git("add", "--", name)
        out = D.preview("git", name)["text"]
        self.assertIn("+literal", out)
        self.assertIn(name, {r["path"] for r in D.index("git")["files"]})

    def test_deleted_files_remain_browsable(self):
        Path("app.py").unlink()
        self.assertIn("app.py", {r["path"] for r in D.index("git")["files"]})
        self.assertIn("-original", D.preview("git", "app.py")["text"])
        self.assertIn("deleted", D.preview("files", "app.py")["text"])

    def test_symlink_and_traversal_refused(self):
        Path("docs/link.md").symlink_to("/etc/hosts")
        for path in ["docs/link.md", "../outside", "/etc/hosts"]:
            with self.assertRaises(RuntimeError):
                D.preview("files", path)

    def test_binary_and_large_file_bounded(self):
        Path("binary").write_bytes(b"A\0B")
        self.assertIn("Binary", D.preview("files", "binary")["text"])
        Path("large.txt").write_bytes(b"a" * (D.LIMIT + 100))
        out = D.preview("files", "large.txt")
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["text"]), D.LIMIT)

    def test_unborn_staged_diff(self):
        self.git("checkout", "--orphan", "fresh")
        self.git("rm", "-rf", ".")
        Path("first.md").write_text("first\n")
        self.git("add", "first.md")
        self.assertIn("+first", D.preview("git", "first.md")["text"])

    def test_clean_tree_browser_still_has_all_files(self):
        self.assertEqual(D.index("git")["files"], [])
        self.assertTrue(D.index("docs")["files"])
        self.assertFalse(any(r["changed"] for r in D.index("files")["files"]))

    def test_tree_groups_and_filters(self):
        files = [dict(path=x) for x in ["a/b.md", "a/c.txt", "root.md"]]
        self.assertEqual(
            [r[:2] for r in P.tree_rows(files)], [("dir", "a"), ("file", "root.md")]
        )
        self.assertEqual(P.tree_rows(files, "a")[0][:2], ("up", ".."))
        self.assertEqual(P.tree_rows(files, query="c.txt")[0][1], "a/c.txt")


class Controls(unittest.TestCase):
    def panel(self):
        p = object.__new__(P.Panel)
        p.cache = {}
        p.last = {}
        p.message = ""
        p.preview = None
        p.address = "box/t2d"
        p.row = {
            "address": p.address,
            "cwd": "/repo",
            "labels": {
                "repo-tools.checkout": "/repo",
                "repo-tools.stream": "feature",
                "repo-tools.role": "work",
                "repo-tools.agent": "claude",
            },
        }
        p.calls = []

        class Backend:
            def work(s, *args):
                p.calls.append(("work", args[1:]))
                return {}

            def hc(s, *args):
                p.calls.append(("hc", args))
                return {}

        p.b = Backend()
        p.busy = lambda title, fn: fn()
        p.confirm = lambda *a: True
        return p

    def test_completion_uses_evidence_only(self):
        p = self.panel()

        def work(*args):
            p.calls.append(args[1:])
            return {"state": "blocked", "checks": []}

        p.b.work = work
        p.check_completion()
        self.assertEqual(
            p.calls, [("complete", "feature", "--status", "--record", "--json")]
        )
        self.assertEqual(p.cache["completion"]["state"], "blocked")

    def test_fresh_chat_cancel_never_sends(self):
        p = self.panel()
        p.confirm = lambda *a: False
        p.new_conversation()
        self.assertFalse(p.calls)

    def test_fresh_chat_targets_same_terminal(self):
        p = self.panel()
        p.b.call = lambda *args: p.calls.append(args) or {"message": "Fresh chat"}
        p.action = lambda a: None
        p.new_conversation()
        self.assertEqual(p.calls[0][1], "repo-new-conversation.py")
        self.assertEqual(p.calls[0][2], ["feature", "--target", "t2d", "--confirm"])

    def test_first_tests_never_launch_claude(self):
        p = self.panel()
        p.cache = {"tests": {"configured": False}}
        p.run_tests()
        args = p.calls[0][1]
        self.assertEqual(args[:3], ("tests", "first", "feature"))
        self.assertEqual(args[-2:], ("--agent", "codex"))
        self.assertNotIn("claude", args)

    def test_existing_tests_reuse_runner(self):
        p = self.panel()
        p.cache = {"tests": {"configured": True}}
        p.run_tests()
        self.assertEqual(p.calls[0][1], ("tests", "run", "feature", "--json"))

    def test_already_running_tests_not_duplicated(self):
        p = self.panel()
        p.cache = {"tests": {"state": "running"}}
        p.run_tests()
        self.assertFalse(p.calls)

    def test_review_budget_exhausted_no_run_option(self):
        p = self.panel()
        p.cache = {"review": {"remaining": 0}}

        def choose(title, rows, hint):
            self.assertNotIn("run", [r[0] for r in rows])
            return None

        p.choose = choose
        p.review_action()
        self.assertFalse(p.calls)

    def test_review_followup_preserves_shared_budget(self):
        p = self.panel()
        p.cache = {"review": {"remaining": 1}}
        p.choose = lambda *a: "run"
        p.review_action()
        args = p.calls[0][1]
        self.assertIn("--follow-up", args)
        self.assertNotIn("--new-cycle", args)

    def test_cancelled_review_does_not_launch(self):
        p = self.panel()
        p.cache = {"review": {"remaining": 2}}
        p.choose = lambda *a: "run"
        p.confirm = lambda *a: False
        p.review_action()
        self.assertFalse(p.calls)

    def test_stale_preview_cannot_replace_selection(self):
        p = self.panel()
        p.address = "t1"
        p.errors = {}
        p.offset = 0
        p.preview_request = "preview:files:new"
        f = concurrent.futures.Future()
        f.set_result({"text": "old"})
        p.pending = {"preview:files:old": ("t1", f)}
        p.collect()
        self.assertIsNone(p.preview)

    def test_explicit_container_cap(self):
        used, limit, pct, capped = C.memory(
            {
                "Metrics": {"MemUsage": "100MiB / 32GiB"},
                "MemoryLimitBytes": 200 * 1024**2,
            }
        )
        self.assertTrue(capped)
        self.assertEqual(pct, 50)

    def test_shared_host_limit_is_not_container_cap(self):
        self.assertFalse(
            C.memory(
                {"Metrics": {"MemUsage": "100MiB / 32GiB"}, "MemoryLimitBytes": 0}
            )[-1]
        )

    def test_launch_reuses_verified_live_pin(self):
        manager = module("manager", "repo-tui")
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            row = {"address": "box/t2d"}
            (state / "top.json").write_text(json.dumps(row))
            (state / "bottom.json").write_text(json.dumps(row))

            class B:
                def hc(self, *args):
                    return {"state": "live"}

                def inventory(self):
                    raise AssertionError("Must not create/reselect live agent")

            with patch.object(manager, "runtime", return_value=state), patch.object(
                manager, "Backend", B
            ):
                manager.seed()
            self.assertEqual(json.loads((state / "top.json").read_text()), row)


import repo_tui_routing as R


class FileRouting(unittest.TestCase):
    def terminal(self, **changes):
        request = dict(v=1, id="a" * 24, root="/repo", path="docs/a.md", time=2000)
        request.update(changes)
        return {"state": "live", "labels": {"repo-read.request": json.dumps(request)}}

    def test_new_request_not_suppressed_by_desktop_ack(self):
        row = self.terminal()
        row["labels"]["repo-read.result"] = json.dumps(
            dict(id="a" * 24, status="shown")
        )
        self.assertIsNotNone(R.pending_request(row, None, 1000))
        self.assertIsNone(R.pending_request(row, None, 3000))

    def test_detached_or_seen_requests_not_replayed(self):
        self.assertIsNone(R.pending_request(self.terminal(), None, None))
        self.assertIsNone(R.pending_request(self.terminal(), "a" * 24, 1000))

    def test_unshown_request_queued_until_viewer_attaches(self):
        self.assertIsNotNone(R.pending_request(self.terminal(), None, 3000))

    def test_invalid_requests_refused(self):
        for change in [
            dict(path="../secret"),
            dict(path="/secret"),
            dict(path="a\0b"),
            dict(id="bad"),
            dict(time=float("nan")),
            dict(v=2),
        ]:
            self.assertIsNone(R.request_for(self.terminal(**change)))

    def test_ack_never_overwrites_new_request_or_success(self):
        class B:
            def __init__(b, row):
                b.row = row
                b.calls = []

            def hc(b, *args):
                b.calls.append(args)
                return b.row

        b = B(self.terminal(id="b" * 24))
        self.assertFalse(R.ack_if_current(b, "t1", "a" * 24, "shown"))
        self.assertEqual(len(b.calls), 1)
        b = B(self.terminal())
        b.row["labels"]["repo-read.result"] = json.dumps(
            dict(id="a" * 24, status="shown")
        )
        self.assertTrue(R.ack_if_current(b, "t1", "a" * 24, "error", "bad"))
        self.assertEqual(len(b.calls), 1)

    def test_success_ack_names_tui_view(self):
        calls = []
        row = self.terminal()

        class B:
            def hc(b, *args):
                calls.append(args)
                return row

        R.ack_if_current(B(), "t1", "a" * 24, "shown", view="files")
        value = json.loads(calls[-1][-1].split("=", 1)[1])
        self.assertEqual(
            (value["viewer"], value["view"], value["status"]), ("tui", "files", "shown")
        )

    def test_stale_or_dead_viewer_lease_is_not_visible(self):
        import time

        with tempfile.TemporaryDirectory() as folder, patch.object(
            C, "runtime", return_value=Path(folder)
        ):
            f = Path(folder) / "viewer-test.json"
            f.write_text(
                json.dumps(
                    dict(pid=os.getpid(), heartbeat=time.time() - 20, started_ms=1)
                )
            )
            self.assertIsNone(C.viewer_started())
            f.write_text(
                json.dumps(dict(pid=os.getpid(), heartbeat=time.time(), started_ms=1))
            )
            self.assertEqual(C.viewer_started(), 1)

    def test_toolbar_right_aligned_at_phone_and_desktop_widths(self):
        for width, labels in [
            (44, ["c Chat", "m Tools ▾", "s Change"]),
            (
                160,
                [
                    "c Chat",
                    "d Docker",
                    "b Docs ▾",
                    "t Tests ▾",
                    "a Actions ▾",
                    "i Info",
                    "s Change",
                ],
            ),
        ]:
            start = R.toolbar_start(width, labels)
            end = start + sum(R.display_width(x) + 2 for x in labels) + len(labels) - 1
            self.assertEqual(end, width - 2)
            self.assertGreater(start, 1)

    def test_source_file_request_rechecks_checkout_and_id(self):
        reader = module("reader", "repo-read")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "note.txt").write_text("same conversation")
            row = self.terminal(root=str(root), path="note.txt")
            row["cwd"] = str(root)
            with patch.object(reader, "hc_json", return_value=row), patch.object(
                reader, "ROOT", root, create=True
            ):
                self.assertEqual(
                    reader.herdr_request("t1", "a" * 24)["text"], "same conversation"
                )
                with self.assertRaises(RuntimeError):
                    reader.herdr_request("t1", "b" * 24)
                row["labels"]["repo-read.request"] = json.dumps(
                    dict(v=1, id="a" * 24, root="/private/tmp", path="note.txt")
                )
                with self.assertRaises(RuntimeError):
                    reader.herdr_request("t1", "a" * 24)

    def test_source_file_request_rejects_symlink_and_binary(self):
        reader = module("reader2", "repo-read")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "link.txt").symlink_to("/etc/hosts")
            (root / "binary.txt").write_bytes(b"x\0y")
            with patch.object(reader, "ROOT", root, create=True):
                for path in ["link.txt", "binary.txt"]:
                    with self.assertRaises(RuntimeError):
                        reader.herdr_file(path)

    def test_case_alias_checkout_routes_on_macos(self):
        reader = module("reader_case", "repo-read")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "Checkout"
            root.mkdir()
            alias = root.with_name("checkout")
            if not alias.exists():
                self.skipTest("Case-sensitive filesystem")
            (root / "note.txt").write_text("checked")
            row = {"state": "live", "cwd": str(alias), "labels": {}}

            def hc(*args):
                if args[0] == "label":
                    req = json.loads(args[-1].split("=", 1)[1])
                    row["labels"]["repo-read.result"] = json.dumps(
                        dict(id=req["id"], status="shown")
                    )
                return row

            with patch.object(reader, "ROOT", root, create=True), patch.object(
                reader, "hc_json", side_effect=hc
            ), patch.dict(os.environ, HC_TERMINAL_ID="t1"), patch("builtins.print"):
                reader.herdr_show("note.txt")

    def test_file_route_uses_existing_tool_pane_and_acks_after_render(self):
        p = object.__new__(P.Panel)
        p.address = "box/t1"
        p.lane = "bottom"
        p.row = {"address": p.address, "cwd": "/repo"}
        p.cache = {"lead": self.terminal()}
        p.errors = {}
        p.route_pending = "route:" + "a" * 24
        p.route_ready = dict(request_id="a" * 24, path="docs/a.md", text="Hello")
        p.route_ack = None
        p.preview = None
        p.tab = "home"
        p.message = ""
        p.calls = []
        p.switch = lambda tab: setattr(p, "tab", tab)
        p.mark_read = lambda rid: p.calls.append(("seen", rid))
        p.fetch = lambda *a, **k: p.calls.append(("fetch", a[0]))

        class B:
            pass

        p.b = B()

        class Screen:
            def getmaxyx(s):
                return (58, 44)

        p.s = Screen()
        with patch.object(P, "state", return_value={}), patch.object(
            P,
            "layout",
            return_value={"bottom": {"panel": "tool", "conversation": "conv"}},
        ), patch.object(P, "native") as native, patch.object(
            P, "viewer_started", return_value=1000
        ):
            p.route_file(1000)
            self.assertEqual(p.tab, "docs")
            self.assertEqual(p.preview["text"], "Hello")
            self.assertFalse(p.calls)
            native.assert_called_once_with(
                "pane", "focus", "--pane", "conv", "--direction", "up"
            )
            p.markdown_visible = False
            p.rendered()
            self.assertFalse(p.calls)
            p.markdown_visible = True
            p.rendered()
            self.assertEqual(
                p.calls, [("seen", "a" * 24), ("fetch", "ack:" + "a" * 24)]
            )


class MarkdownReader(unittest.TestCase):
    def text(self, lines):
        return "\n".join("".join(s[0] for s in line) for line in lines)

    def test_real_glow_formats_headings_emphasis_lists_and_code(self):
        m = P.MD
        lines = m.render(
            '# Phone heading\n\nA **bold** and *italic* paragraph.\n\n## Tasks\n\n- [x] Done\n- [ ] Next\n  - Nested\n\n```python\nprint("hello")\n```\n',
            38,
        )
        text = self.text(lines)
        self.assertNotIn("# Phone", text)
        self.assertNotIn("**", text)
        self.assertNotIn("```", text)
        for word in (
            "Phone heading",
            "Tasks",
            "Done",
            "Next",
            "Nested",
            'print("hello")',
        ):
            self.assertIn(word, text)
        self.assertTrue(
            any(
                "Phone heading" in t and f & m.BOLD and c
                for line in lines
                for t, f, c in line
            )
        )
        self.assertTrue(
            any(t == "bold" and f & m.BOLD for line in lines for t, f, c in line)
        )

    def test_phone_resize_preserves_long_code_links_and_unicode(self):
        m = P.MD
        code = "abcdefghij" * 12
        source = (
            "# Résumé\n\n界界 café e\u0301\n\n[Reference](https://example.com/"
            + code
            + ")\n\n```\n"
            + code
            + "\n```"
        )
        for width in (26, 38, 100):
            lines = m.render(source, width)
            self.assertTrue(
                all(m.cells("".join(s[0] for s in line)) <= width for line in lines)
            )
            compact = "".join(self.text(lines).split())
            self.assertIn(code, compact)
            self.assertIn("https://example.com/" + code, compact)
            self.assertIn("界界", compact)

    def test_tables_quotes_and_reference_links_keep_content(self):
        source = "> A quote\n\n| Item | Result |\n| --- | --- |\n| Docs | Passed |\n| Phone | Wrapped |\n\n[Details][ref]\n\n[ref]: https://example.com/docs\n"
        text = self.text(P.MD.render(source, 38))
        for word in (
            "A quote",
            "Item",
            "Result",
            "Docs",
            "Passed",
            "Phone",
            "Wrapped",
            "Details",
            "https://example.com/docs",
        ):
            self.assertIn(word, text)
        self.assertNotIn("[ref]", text)

    def test_terminal_controls_never_reach_curses(self):
        lines = P.MD.spans(
            "Hello\x1b]52;c;secret\x07\x1b[2J\x1b[31m red\x1b[0m\x1b]8;;https://example.com\x1b\\ link\x1b]8;;\x1b\\",
            38,
        )
        text = self.text(lines)
        self.assertEqual(text, "Hello red link")
        self.assertNotIn("\x1b", text)
        self.assertTrue(any(c == 4 for line in lines for _, _, c in line))

    def test_only_docs_markdown_uses_formatter_and_source_toggle_works(self):
        p = object.__new__(P.Panel)
        p.tab = "docs"
        p.preview = {"path": "docs/brief.md"}
        p.markdown_source = False
        p.offset = 8
        self.assertTrue(p.formatted_markdown())
        p.key("v")
        self.assertFalse(p.formatted_markdown())
        self.assertEqual(p.offset, 0)
        p.key("v")
        self.assertTrue(p.formatted_markdown())
        p.preview["path"] = "docs/note.txt"
        self.assertFalse(p.formatted_markdown())
        p.preview["path"] = "docs/brief.md"
        p.tab = "files"
        self.assertFalse(p.formatted_markdown())
        p.tab = "git"
        self.assertFalse(p.formatted_markdown())

    def test_scroll_reuses_render_and_environment_disables_pager(self):
        m = P.MD
        m.render.cache_clear()
        with patch.object(
            m.sp, "run", return_value=subprocess.CompletedProcess([], 0, "Readable", "")
        ) as run, patch.object(m, "glow_binary", return_value="/bin/glow"):
            m.render("# Cached", 38)
            m.render("# Cached", 38)
            self.assertEqual(run.call_count, 1)
            m.render("# Cached", 100)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.kwargs["env"]["GLOW_PAGER"], "false")
            self.assertEqual(run.call_args.args[0][-1], "-")
        m.render.cache_clear()


class DocumentNavigation(unittest.TestCase):
    def test_relative_reference_and_escape_links(self):
        text = "[Other](../other.md#section) [Ref][r] [outside](../../../secret) [web](https://example.com) [bad](javascript:alert)\n\n[r]: notes.txt\n"
        self.assertEqual(
            P.MD.file_links(text, "docs/topic/start.md"),
            [
                ("Other", "docs/other.md", "section"),
                ("Ref", "docs/topic/notes.txt", ""),
            ],
        )

    def test_back_restores_document_scroll_and_source(self):
        p = object.__new__(P.Panel)
        old = {"path": "docs/a.md", "text": "hello"}
        p.doc_history = [("docs", old, 42, "docs", 3, True)]
        p.preview = {}
        p.offset = 0
        p.document_back()
        self.assertIs(p.preview, old)
        self.assertEqual(p.offset, 42)
        self.assertEqual(p.folder, "docs")
        self.assertTrue(p.markdown_source)
        self.assertTrue(p.preview_focus)
        self.assertFalse(p.doc_history)

    def test_encoded_parent_escape_refused(self):
        self.assertEqual(P.MD.file_links("[x](%2e%2e/%2e%2e/secret)", "docs/a.md"), [])


if __name__ == "__main__":
    unittest.main()
