"""Keyboard/mouse tool panels. Every mutation uses the existing workflow controller."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import curses
import datetime
import json
import os
from pathlib import Path
import subprocess as sp
import textwrap
import time
import re
import repo_stream_picker as W
from repo_terminal_ui import UI, clean, clipped
from repo_tui_common import (
    Backend, bar, control, focus_conversation, lane_state, layout, level,
    memory, native, pane_id, reset_note, runtime, save, state, status, update,
    viewer_started,
)
from repo_tui_routing import (
    DOCS,
    request_for,
    pending_request,
    ack_if_current,
    display_width,
    toolbar_start,
)
import repo_tui_markdown as MD

PRESETS = {
    "investigate-failure": (
        "Investigate failure",
        "Explain the failure, distinguish evidence from hypotheses, and propose the smallest next check or fix.",
    ),
    "campaign-follow-up": (
        "Campaign follow-up",
        "Review campaign performance for these dates and suggest one measurable next experiment.",
    ),
    "pre-publication": (
        "Pre-publication check",
        "Check claims, links, tracking, consistency and missing assets. Separate blockers from suggestions.",
    ),
}
INFO = {
    "agents": "Agents",
    "context": "Context",
    "usage": "Usage",
    "services": "Containers",
    "git-info": "Git status",
}


def tree_rows(files, folder="", query=""):
    source = [r for r in files if query.lower() in r["path"].lower()]
    if query:
        return [("file", r["path"], r) for r in source]
    prefix = folder + "/" if folder else ""
    source = [r for r in source if r["path"].startswith(prefix)]
    dirs = sorted(
        {
            r["path"][len(prefix) :].split("/")[0]
            for r in source
            if "/" in r["path"][len(prefix) :]
        }
    )
    rows = [("up", "..", {})] if folder else []
    rows += [("dir", prefix + d, {}) for d in dirs]
    rows += [
        ("file", r["path"], r) for r in source if "/" not in r["path"][len(prefix) :]
    ]
    return rows


def lines_for(text, width):
    lines = []
    for raw in str(text).splitlines():
        lines.extend(
            textwrap.wrap(
                clean(raw).expandtabs(4),
                max(8, width),
                replace_whitespace=False,
                drop_whitespace=False,
            )
            or [""]
        )
    return lines or [""]


def test_line(row):
    code = row.get("exit_code")
    summary = row.get("native_summary") or {}
    mark = "✓" if code == 0 else "…" if code is None else "✗"
    summary = (
        " · ".join(
            f"{k}: {v}" for k, v in summary.items() if isinstance(v, (int, float, str))
        )
        if isinstance(summary, dict)
        else str(summary)
    )
    return f"{mark} {row['id']}  {summary or ('Exit '+str(code))}", (
        2 if code == 0 else 3 if code is None else 4
    )


class Panel:
    def __init__(self, screen, lane, view):
        self.ui = UI(screen)
        self.s = screen
        self.lane = lane
        self.view = view
        self.b = Backend()
        self.row = {}
        self.tab = "agents" if view == "info" else "home"
        self.cache = {}
        self.errors = {}
        self.last = {}
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.pending = {}
        self.index = 0
        self.offset = 0
        self.folder = ""
        self.query = ""
        self.preview = None
        self.preview_focus = False
        self.force_all = False
        self.frozen = False
        self.follow = True
        self.buttons = []
        self.rows = []
        self.message = ""
        self.request = None
        self.geometry = None
        self.reported = None
        self.last_lead = 0
        self.close_requested = False
        self.click_rows = []
        self.address = None
        self.preview_request = None
        self.reported_at = 0
        self.route_pending = None
        self.route_ready = None
        self.route_ack = None
        self.selected_path = None
        self.doc_history = []
        self.checkpoint_notice = None
        self.markdown_source = False
        self.markdown_key = None
        self.markdown_future = None
        self.markdown_visible = False
        self.s.timeout(150)
        curses.mouseinterval(0)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
        except curses.error:
            pass

    def fetch(self, key, fn, period=10, force=False):
        if key in self.pending:
            return
        if not force and time.monotonic() - self.last.get(key, 0) < period:
            return
        self.last[key] = time.monotonic()
        self.pending[key] = (self.address, self.pool.submit(fn))

    def collect(self):
        for key, (address, f) in list(self.pending.items()):
            if not f.done():
                continue
            del self.pending[key]
            if address != self.address:
                continue
            try:
                self.cache[key] = f.result()
                self.errors.pop(key, None)
                if key == "checkpoint":
                    job = self.cache[key]
                    op = job.get("operation", {})
                    stamp = op.get("event_id")
                    if op.get("notification") and stamp != self.checkpoint_notice:
                        self.checkpoint_notice = stamp
                        self.message = job.get("message", "")
                        try:
                            curses.beep()
                        except curses.error:
                            pass
                if key.startswith("preview:") and key == self.preview_request:
                    self.preview = self.cache[key]
                    self.offset = 0
                elif key.startswith("route:") and key == self.route_pending:
                    self.route_ready = self.cache[key]
            except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
                self.errors[key] = str(e)

    def sync(self):
        row = lane_state(self.lane)
        if row.get("address") != self.address:
            self.row = row
            self.address = row.get("address")
            self.cache = {}
            self.errors = {}
            self.last = {}
            self.preview = None
            self.folder = ""
            self.index = 0
            self.route_pending = None
            self.route_ready = None
            self.route_ack = None
            self.doc_history = []
        c = state(self.lane)
        if self.view == "info":
            self.tab = c.get("info_tab", "agents")
        elif c.get("request") != self.request:
            self.request = c.get("request")
            action = c.get("command")
            control(self.lane, command=None)
            if action:
                self.action(action)
        if not self.row:
            return
        row = dict(self.row)
        attached = viewer_started() if self.view == "panel" else None
        self.fetch(
            "lead", lambda: self.b.hc("get", row["address"]), 1 if attached else 5
        )
        tab = self.tab
        if self.view == "panel":
            self.fetch(
                "checkpoint",
                lambda: self.b.call(
                    row,
                    "repo-new-conversation.py",
                    [W.label(row, "stream"), "--status"],
                ),
                3,
            )
        if tab in ("docs", "files", "git"):
            self.fetch(tab, lambda: self.b.data(row, tab), 10)
        elif tab == "docker":
            if not self.frozen:

                def logs():
                    d = self.b.work(
                        row,
                        "observe",
                        W.label(row, "stream"),
                        "--json",
                        "--status-only",
                    )
                    if d.get("state") == "active":
                        d.update(
                            self.b.call(
                                row, "repo-logfeed.py", ["poll", W.label(row, "stream")]
                            )
                        )
                    return d

                self.fetch("docker", logs, 2)
        elif tab == "tests":
            self.fetch(
                tab,
                lambda: self.b.work(
                    row, "tests", "status", W.label(row, "stream"), "--json"
                ),
                5,
            )
        elif tab == "review":
            self.fetch(
                tab,
                lambda: self.b.work(
                    row, "review", W.label(row, "stream"), "--status", "--json"
                ),
                5,
            )
            self.fetch(
                "completion",
                lambda: self.b.work(
                    row, "complete", W.label(row, "stream"), "--status", "--json"
                ),
                15,
            )
        elif tab in ("agents", "questions"):
            self.fetch(
                "agents",
                lambda: self.b.data(row, "agents", row["address"].rsplit("/", 1)[-1]),
                5,
            )
            self.fetch(
                "metadata",
                lambda: self.b.call(
                    row,
                    "repo-panel.py",
                    ["metadata", row["address"].rsplit("/", 1)[-1]],
                ),
                30,
            )
        elif tab in ("context", "usage"):
            self.fetch(
                "metadata",
                lambda: self.b.call(
                    row,
                    "repo-panel.py",
                    ["metadata", row["address"].rsplit("/", 1)[-1]],
                ),
                30,
            )
            if tab == "usage":
                self.fetch(
                    "usage",
                    lambda: self.b.call(row, "repo-provider.py", ["status"]),
                    30,
                )
                self.fetch(
                    "review",
                    lambda: self.b.work(
                        row, "review", W.label(row, "stream"), "--status", "--json"
                    ),
                    30,
                )
        elif tab == "services":
            self.fetch(
                tab,
                lambda: self.b.work(
                    row,
                    "observe",
                    W.label(row, "stream"),
                    "--json",
                    "--status-only",
                    "--metrics",
                ),
                15,
            )
        elif tab == "git-info":
            self.fetch("git", lambda: self.b.data(row, "git"), 10)
        self.collect()
        if self.view == "panel":
            self.route_file(attached)
            self.report()

    def mark_read(self, request_id):
        # Separate IDs per conversation; changing streams never replays its old request.
        def changed(d):
            seen = d.get("read_seen", {})
            seen[self.address] = request_id
            return dict(d, read_seen=dict(list(seen.items())[-50:]))

        update(self.lane + "-control", changed)

    def route_file(self, attached):
        lead = self.cache.get("lead", {})
        seen = state(self.lane).get("read_seen", {}).get(self.address)
        request = pending_request(lead, seen, attached)
        if not request:
            return
        key = "route:" + request["id"]
        row = dict(self.row)
        address = self.address
        if self.route_pending != key:
            self.route_pending = key
            self.route_ready = None
            self.fetch(
                key,
                lambda: self.b.call(
                    row,
                    "repo-read",
                    ["--herdr-request", address.rsplit("/", 1)[-1], request["id"]],
                ),
                force=True,
            )
        if self.errors.get(key):
            self.message = "Could not open requested file: " + self.errors[key]
            self.mark_read(request["id"])
            message = self.errors[key]
            self.fetch(
                "ack:" + request["id"],
                lambda: ack_if_current(
                    self.b, address, request["id"], "error", message
                ),
                force=True,
            )
            return
        if not self.route_ready:
            return
        document = self.route_ready
        self.route_ready = None
        if document.get("request_id") != request["id"]:
            return
        view = "docs" if Path(document["path"]).suffix.lower() in DOCS else "files"
        self.switch(view)
        self.preview = document
        self.preview_focus = True
        self.selected_path = document["path"]
        self.folder = str(Path(document["path"]).parent)
        if self.folder == ".":
            self.folder = ""
        self.message = "Requested file: " + document["path"]
        d = layout().get(self.lane, {})
        # Focus the existing tool panel; never send text or restart the conversation.
        native("pane", "focus", "--pane", d["conversation"], "--direction", "up")
        self.route_ack = (address, request["id"], view)

    def rendered(self):
        if not self.route_ack or viewer_started() is None:
            return
        address, request_id, view = self.route_ack
        if address != self.address or not self.preview or self.tab != view:
            return
        h, w = self.s.getmaxyx()
        if h < 9 or w < 24:
            return
        if self.formatted_markdown() and not self.markdown_visible:
            return
        self.route_ack = None
        self.mark_read(request_id)
        self.fetch(
            "ack:" + request_id,
            lambda: ack_if_current(self.b, address, request_id, "shown", view=view),
            force=True,
        )

    def report(self):
        lead = self.cache.get("lead")
        d = layout().get(self.lane, {})
        if not lead or not d.get("conversation"):
            return
        s = status(lead)
        identity = (self.address, s, lead.get("title"))
        if identity == self.reported and time.monotonic() - self.reported_at < 10:
            return
        self.reported = identity
        self.reported_at = time.monotonic()
        try:
            # Display state only: no agent start/resume command is registered with native TUI.
            native(
                "pane",
                "report-agent",
                d["conversation"],
                "--source",
                "repo-dashboard",
                "--agent",
                W.label(self.row, "agent", "agent"),
                "--state",
                (
                    s
                    if s in ("idle", "working", "blocked")
                    else "idle" if s == "done" else "unknown"
                ),
                "--message",
                s,
            )
            native(
                "pane",
                "report-metadata",
                d["conversation"],
                "--source",
                "repo-dashboard",
                "--title",
                clean(lead.get("title") or W.label(self.row, "stream")),
                "--state-label",
                "idle=" + s,
                "--token",
                "stream=" + W.label(self.row, "stream"),
                "--ttl-ms",
                "15000",
            )
        except (RuntimeError, OSError, sp.SubprocessError):
            pass

    def fit(self, force=False):
        if self.view != "panel":
            return
        h, w = self.s.getmaxyx()
        key = (self.tab, w)
        if key == self.geometry and not force:
            return
        self.geometry = key
        d = layout().get(self.lane, {})
        if not d.get("panel"):
            return
        info = d.get("info")
        if info and w < 85:
            native("pane", "close", info)
            update(
                "layout",
                lambda x: dict(
                    x,
                    **{
                        self.lane: {
                            k: v for k, v in x[self.lane].items() if k != "info"
                        }
                    },
                ),
            )
        if w < 80 and self.tab != "home":
            native("pane", "zoom", d["panel"], "--on")
            return
        native("pane", "zoom", d["panel"], "--off")
        data = native("pane", "layout", "--pane", d["panel"])["layout"]
        rect = next(p["rect"] for p in data["panes"] if p["pane_id"] == d["panel"])
        parents = [
            s
            for s in data["splits"]
            if s["direction"] == "down"
            and s["rect"]["x"] == rect["x"]
            and s["rect"]["y"] == rect["y"]
            and s["rect"]["width"] == rect["width"]
        ]
        if not parents:
            return
        parent = min(parents, key=lambda s: s["rect"]["height"])
        desired = (
            min(0.65, 6 / parent["rect"]["height"]) if self.tab == "home" else 0.55
        )
        diff = desired - parent["ratio"]
        # Resize the shared internal edge, never an outer edge of the stream.
        if abs(diff) > 0.015:
            native(
                "pane",
                "resize",
                "--pane",
                d["panel"] if diff > 0 else d["conversation"],
                "--direction",
                "down" if diff > 0 else "up",
                "--amount",
                str(abs(diff)),
            )

    def switch(self, tab):
        self.tab = tab
        self.index = 0
        self.offset = 0
        self.preview = None
        self.folder = ""
        self.query = ""
        self.preview_focus = False
        self.preview_request = None
        self.markdown_source = False
        self.message = ""
        self.fit(True)

    def dialog(self, fn):
        d = layout().get(self.lane, {})
        pane = d.get("info") if self.view == "info" else d.get("panel")
        if pane:
            native("pane", "zoom", pane, "--on")
        self.s.timeout(-1)
        try:
            return fn()
        finally:
            self.s.timeout(150)
            if pane:
                native("pane", "zoom", pane, "--off")
            self.geometry = None
            self.fit(True)

    def choose(self, title, rows, hint=""):
        return self.dialog(lambda: self.ui.choose(title, rows, hint))

    def confirm(self, title, hint):
        return (
            self.choose(
                title, [("no", "Cancel", "No action"), ("yes", "Continue", hint)], hint
            )
            == "yes"
        )

    def busy(self, title, fn):
        return self.dialog(lambda: self.ui.busy(title, fn))

    def action(self, name):
        if name == "home":
            self.switch("home")
            control(self.lane, reattach=True, detached=False)
            focus_conversation(self.lane)
            return
        if name == "retry-checkpoint":
            return self.retry_checkpoint()
        if name == "completion":
            return self.check_completion()
        if name == "menu":
            name = self.choose(
                "Tools",
                [
                    ("home", "● Conversation", "Return to the same agent"),
                    ("questions", "? Questions", "Agents awaiting input"),
                    ("docker", "▤ Docker", "Live logs and start"),
                    ("browse", "▣ Docs / Files / Git", "Directory tree and preview"),
                    (
                        "checks",
                        "✓ Tests / Review",
                        "Project checks and bounded Claude review",
                    ),
                    ("info", "◉ Information", "Agents, context, usage, containers"),
                    ("actions", "☷ Actions", "Workflow and helpers"),
                    (
                        "pick",
                        "↔ Change stream",
                        "Existing conversations, worktrees or new stream",
                    ),
                ],
            )
            if not name:
                return
        if name == "browse":
            name = self.choose(
                "Browse",
                [
                    ("docs", "Docs", "Markdown and text"),
                    ("files", "Files", "All repository files"),
                    ("git", "Git", "Staged and unstaged changes"),
                ],
            )
        elif name == "checks":
            name = self.choose(
                "Checks",
                [
                    ("tests", "Tests", "Project test results and logs"),
                    ("review", "Review", "Independent, limited Claude review"),
                ],
            )
        if not name:
            return
        if name in ("home", "menu"):
            return self.action(name)
        if name == "info":
            chosen = self.choose(
                "Information",
                [(k, v, "Reported data only") for k, v in INFO.items()]
                + [("hide", "Hide information", "Keep conversation visible")],
            )
            if not chosen:
                return
            d = layout().get(self.lane, {})
            if chosen == "hide":
                if d.get("info"):
                    native("pane", "close", d["info"])
                    update(
                        "layout",
                        lambda x: dict(
                            x,
                            **{
                                self.lane: {
                                    k: v for k, v in x[self.lane].items() if k != "info"
                                }
                            },
                        ),
                    )
                return
            control(self.lane, info_tab=chosen)
            if self.view == "info":
                self.tab = chosen
                return
            if self.s.getmaxyx()[1] >= 110:
                if not d.get("info"):
                    r = native(
                        "pane",
                        "split",
                        d["conversation"],
                        "--direction",
                        "right",
                        "--ratio",
                        "0.73",
                        "--cwd",
                        str(Path.home()),
                        "--env",
                        "REPO_TUI_LANE=" + self.lane,
                        "--env",
                        "REPO_TUI_VIEW=info",
                        "--no-focus",
                    )
                    update(
                        "layout",
                        lambda x: dict(
                            x, **{self.lane: dict(x[self.lane], info=pane_id(r))}
                        ),
                    )
                return
            return self.switch(chosen)
        if name == "pick":
            args = argparse.Namespace(
                machine=W.machine(self.row["address"]) if self.row else None,
                repo=W.label(self.row, "checkout") if self.row else None,
                role=(
                    W.label(self.row, "role")
                    if self.row
                    else "studio" if self.lane == "top" else "work"
                ),
                select_only=True,
                current=self.address,
            )
            picker = W.Picker(self.b, self.ui, args)
            self.dialog(picker.run)
            if picker.result:
                save(runtime() / (self.lane + ".json"), picker.result)
                self.sync()
                self.action("home")
            return
        if not self.row:
            self.message = "Choose a stream first (s)."
            return
        if name == "actions":
            ch = self.choose(
                "Actions",
                [
                    (
                        "new-chat",
                        "New conversation · same stream",
                        "Save handoff, commit/push checkpoint, then fresh chat",
                    ),
                    (
                        "checkpoint",
                        "Checkpoint progress",
                        "Saving context → commit → push → verify → restart",
                    ),
                    (
                        "workflow",
                        "Workflow actions",
                        "Studio, Work, implement through review",
                    ),
                    (
                        "helper",
                        "Ask a helper about this",
                        "Read-only Codex/Cursor with selected pane evidence",
                    ),
                    (
                        "pick",
                        "Change stream",
                        "Attach or create with the shared picker",
                    ),
                ],
            )
            if ch == "checkpoint":
                self.switch("checkpoint")
                self.last["checkpoint"] = 0
            if ch == "workflow":
                self.dialog(
                    lambda: self.ui.outside(
                        lambda: self.b.actions(
                            W.machine(self.address),
                            W.label(self.row, "checkout"),
                            W.label(self.row, "role"),
                        )
                    )
                )
            elif ch == "new-chat":
                self.new_conversation()
            elif ch == "helper":
                self.helper()
            elif ch == "pick":
                self.action("pick")
            return
        self.switch(name)

    def new_conversation(self):
        if not self.row:
            return
        if not self.confirm(
            "Fresh conversation, same stream?",
            "Ask the agent to save context, commit intended changes and push this stream branch. Restart only after verification; no tests or review.",
        ):
            return
        result = self.busy(
            "Opening fresh conversation…",
            lambda: self.b.call(
                self.row,
                "repo-new-conversation.py",
                [
                    W.label(self.row, "stream"),
                    "--target",
                    self.address.rsplit("/", 1)[-1],
                    "--confirm",
                ],
            ),
        )
        self.message = result["message"]
        self.last["checkpoint"] = 0
        self.action("home")

    def retry_checkpoint(self):
        job = self.cache.get("checkpoint", {})
        if not job.get("operation", {}).get("can_retry"):
            self.message = job.get("message", "No failed checkpoint to retry.")
            return
        if not self.confirm(
            "Retry unfinished checkpoint?",
            "Recheck saved context, commits and remote branch; preserve completed work.",
        ):
            return
        result = self.busy(
            "Retrying checkpoint…",
            lambda: self.b.call(
                self.row,
                "repo-new-conversation.py",
                [
                    W.label(self.row, "stream"),
                    "--target",
                    job["target"],
                    "--retry",
                    job["token"],
                ],
            ),
        )
        self.message = result.get("message", "Retry requested")
        self.last["checkpoint"] = 0

    def check_completion(self):
        if not self.row:
            return
        result = self.busy(
            "Checking existing evidence only…",
            lambda: self.b.work(
                self.row,
                "complete",
                W.label(self.row, "stream"),
                "--status",
                "--record",
                "--json",
            ),
        )
        self.cache["completion"] = result
        self.message = result["state"] + " · No tests or Claude started"
        self.offset = 0

    def helper(self):
        evidence = self.evidence()
        if not evidence[1].strip():
            self.message = "Select a file, log, test result or report first."
            return
        preset = self.choose(
            "Read-only helper",
            [(k, v[0], v[1]) for k, v in PRESETS.items()],
            "No Claude usage. One helper at a time.",
        )
        if not preset:
            return
        agent = self.choose(
            "Helper model",
            [
                ("codex", "Codex", "Read-only investigator"),
                ("cursor", "Cursor", "Read-only investigator"),
            ],
        )
        if not agent:
            return
        question = self.dialog(lambda: self.ui.input("Question", PRESETS[preset][1]))
        if not question:
            return
        text = evidence[1]
        pane = evidence[0]
        packet = dict(
            version=1,
            pane=pane,
            cwd=W.label(self.row, "checkout"),
            stream=W.label(self.row, "stream"),
            parent=self.address.rsplit("/", 1)[-1],
            source=self.preview.get("path") if self.preview else pane,
            captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            text=text[-18000:] if pane == "docker" else text[:18000],
            truncated=len(text) > 18000,
            draft=False,
        )
        args = [
            "flow",
            "helper",
            W.label(self.row, "stream"),
            "--role",
            W.label(self.row, "role"),
            "--kind",
            "research",
            "--agent",
            agent,
            "--preset",
            preset,
            "--scope",
            question,
            "--context-json",
            json.dumps(packet),
        ]
        if preset == "campaign-follow-up":
            for flag, title in [
                ("--period", "Reporting dates YYYY-MM-DD..YYYY-MM-DD"),
                ("--compare-period", "Comparison dates (same length)"),
            ]:
                value = self.dialog(lambda: self.ui.input(title))
                if not value:
                    return
                args += [flag, value]
        role = W.label(self.row, "role")
        self.busy(
            "Validating helper context…",
            lambda: self.b.call(self.row, role, [*args, "--preview"], raw=True),
        )
        if not self.confirm(
            "Start read-only helper?",
            agent + " · " + PRESETS[preset][0] + " · selected pane excerpt",
        ):
            return
        # Never retry a launch automatically: a timeout may have created its terminal.
        out = self.busy(
            "Opening helper…", lambda: self.b.call(self.row, role, args, raw=True)
        )
        self.message = clean(out)
        self.last["agents"] = 0

    def run_tests(self):
        d = self.cache.get("tests", {})
        if d.get("state") in ("queued", "running", "preparing"):
            self.message = "Tests are already running."
            return
        if not self.confirm(
            "Run project tests?", "First setup uses a Codex/Cursor child. No Claude."
        ):
            return
        args = [
            "tests",
            "run" if d.get("configured") else "first",
            W.label(self.row, "stream"),
            "--json",
        ]
        if not d.get("configured"):
            args += [
                "--target",
                self.address.rsplit("/", 1)[-1],
                "--agent",
                "cursor" if W.label(self.row, "agent") == "cursor" else "codex",
            ]
        self.busy("Queuing tests…", lambda: self.b.work(self.row, *args))
        self.last["tests"] = 0
        self.message = "Tests queued. Results refresh here."

    def review_action(self):
        d = self.cache.get("review", {})
        left = d.get("remaining")
        rows = [
            (
                "complete",
                "Check completion",
                "Use existing evidence; no tests or Claude",
            ),
            ("doctor", "Check setup", "Authentication and required inputs"),
            ("prepare", "Prepare inputs", "No Claude call"),
        ]
        if (
            isinstance(left, int)
            and left > 0
            and d.get("state") not in ("reviewing", "preflight")
        ):
            rows += [
                (
                    "run",
                    "Start review" if left == 2 else "Follow-up review",
                    str(left) + " calls left in this cycle",
                )
            ]
        ch = self.choose(
            "Review actions",
            rows,
            "Same shared budget: 1 initial + 1 follow-up. No automatic reset.",
        )
        if not ch:
            return
        stream = W.label(self.row, "stream")
        if ch == "complete":
            return self.check_completion()
        if ch == "doctor":
            out = self.busy(
                "Checking setup…",
                lambda: self.b.work(self.row, "review", stream, "--doctor", "--json"),
            )
            self.preview = {"path": "Review setup", "text": json.dumps(out, indent=2)}
            self.offset = 0
            return
        if ch == "run" and not self.confirm(
            "Start bounded Claude review?",
            f"{left} calls remain. 24 turns / 20 minutes per call.",
        ):
            return
        args = ["review", stream] + (
            ["--prepare"] if ch == "prepare" else ["--follow-up"] if left == 1 else []
        )
        on = W.machine(self.address)
        job = self.busy(
            "Queuing review controller…",
            lambda: self.b.hc(
                "run",
                *(["--on", on] if on else []),
                "--bg",
                "--no-parent",
                "--no-notify",
                "--cwd",
                W.label(self.row, "checkout"),
                "--label",
                "repo-tools.kind=review-control",
                "--",
                "python3",
                "-c",
                'import os,sys; from pathlib import Path; p=Path.home()/".local/bin/work"; os.environ["PATH"]=os.pathsep.join([str(p.parent),"/usr/local/bin","/opt/homebrew/bin",os.environ.get("PATH","/usr/bin:/bin")]); os.execv(str(p),[str(p),*sys.argv[1:]])',
                *args,
            ),
        )
        self.message = "Review controller queued. Refresh for its result."
        self.last["review"] = 0

    def evidence(self):
        pane = {
            "git": "changes",
            "docs": "docs",
            "files": "files",
            "tests": "tests",
            "review": "review",
            "docker": "docker",
        }.get(self.tab, self.tab)
        if self.preview:
            return pane, self.preview.get("text", "")
        d = self.cache.get(self.tab, {})
        return pane, (
            d.get("logs", "")
            if self.tab == "docker"
            else d.get("report_markdown", "") if self.tab == "review" else ""
        )

    def copy(self):
        text = self.evidence()[1]
        if not text:
            self.message = "Select content first."
            return
        encoded = base64.b64encode(text[:100000].encode()).decode()
        self.ui.outside(
            lambda: print("\033]52;c;" + encoded + "\a", end="", flush=True)
        )
        self.message = "Copy requested from your terminal (up to 100,000 characters)."

    def button(self, y, x, label, action, color=1):
        w = self.s.getmaxyx()[1]
        text = " " + label + " "
        width = display_width(text)
        if x + width >= w:
            return x
        self.ui.put(y, x, text, curses.A_REVERSE | self.ui.color(color))
        self.buttons.append((y, x, x + width, action))
        return x + width + 1

    def header(self):
        h, w = self.s.getmaxyx()
        lead = self.cache.get("lead", self.row)
        s = status(lead)
        color = (
            4
            if s in ("error", "failed")
            else 3 if s in ("blocked", "done") else 2 if s == "working" else 1
        )
        title = (
            self.row.get("project_name", "") + " / " + W.label(self.row, "stream")
        ).strip(" /") or "Choose stream"
        self.ui.put(
            0,
            1,
            title + " · " + W.label(self.row, "role") + " · " + s,
            curses.A_BOLD | self.ui.color(color),
        )
        browser = self.tab.title() if self.tab in ("docs", "files", "git") else "Docs"
        checks = "Review" if self.tab == "review" else "Tests"
        items = (
            [
                ("c Chat", "home"),
                ("d Docker", "docker"),
                ("b " + browser + " ▾", "browse"),
                ("t " + checks + " ▾", "checks"),
                ("a Actions ▾", "actions"),
                ("i Info", "info"),
                ("s Change", "pick"),
            ]
            if w >= 100
            else [("c Chat", "home"), ("m Tools ▾", "menu"), ("s Change", "pick")]
        )
        if self.view == "info":
            items = [
                ("i Views ▾", "info"),
                ("r Refresh", "refresh"),
                ("x Hide", "hide-info"),
            ]
        x = toolbar_start(w, [item[0] for item in items])
        for label, act in items:
            x = self.button(1, x, label, act)
        if self.tab == "home":
            self.ui.put(
                2,
                1,
                (
                    self.cache.get("checkpoint", {}).get("message")
                    if self.cache.get("checkpoint", {}).get("target")
                    == self.address.rsplit("/", 1)[-1]
                    else None
                )
                or self.message
                or "Ctrl+B t: tools · Ctrl+B z: maximize · Ctrl+B ↑/↓: move",
                curses.A_DIM,
            )
        elif h > 4:
            hints = {
                "docs": "a All/modified · / Filter · Enter open · Tab preview",
                "files": "a All/modified · / Filter · Enter open · Tab preview",
                "git": "Enter diff · Tab preview · / Filter",
                "docker": "p Freeze · End follow · y Copy · R Start",
                "tests": "R Run tests · Enter logs · h Helper",
                "review": "K Check completion · R Review actions",
                "questions": "Enter: open the exact question",
                "agents": "Enter: open agent · Ctrl+\\: return",
            }
            self.ui.put(
                2,
                1,
                self.tab.title() + " · " + hints.get(self.tab, "r Refresh · ↑↓ scroll"),
                self.ui.color(1),
            )
            if self.tab == "review":
                self.button(3, max(1, w - 24), "K Check completion", "completion")
            if (
                self.tab == "docs"
                and self.preview
                and Path(self.preview["path"]).suffix.lower() in MD.MARKDOWN
            ):
                self.ui.put(2, 1, " " * (w - 2))
                self.ui.put(
                    2,
                    1,
                    (
                        "Docs · Source · v Format"
                        if self.markdown_source
                        else "Docs · Formatted · v Source"
                    )
                    + " · Tab files",
                    self.ui.color(1),
                )
        job = self.cache.get("checkpoint", {})
        if job.get("target") == (self.address or "").rsplit("/", 1)[-1] and job.get(
            "state"
        ):
            op = job.get("operation", {})
            bad = op.get("failed")
            stage = op.get("label", job["state"])
            text = (
                ("! " if bad else "✓ " if job["state"] == "started" else "… ")
                + str(stage)
                + " · "
                + str(job.get("elapsed_seconds", 0))
                + "s · "
                + job.get("message", "")
            )
            self.ui.put(2, 1, " " * (w - 2))
            self.ui.put(
                2,
                1,
                text,
                self.ui.color(4 if bad else 2 if job["state"] == "started" else 3),
            )
        if self.tab == "checkpoint" and job.get("operation", {}).get("can_retry"):
            self.button(
                3, max(1, w - 25), "Retry unfinished step", "retry-checkpoint", 3
            )
        return 4

    def paint_text(self, text, y, x, height, width, follow=False):
        lines = lines_for(text, width - 1)
        end = max(0, len(lines) - height)
        self.offset = end if follow else min(max(0, self.offset), end)
        for i, line in enumerate(lines[self.offset : self.offset + height]):
            color = (
                2
                if self.tab == "git"
                and line.startswith("+")
                and not line.startswith("+++")
                else (
                    4
                    if self.tab == "git"
                    and line.startswith("-")
                    and not line.startswith("---")
                    else 0
                )
            )
            self.ui.put(
                y + i,
                x,
                clipped(line, width - 1),
                self.ui.color(color) if color else 0,
            )
        return end

    def formatted_markdown(self):
        return (
            self.tab == "docs"
            and self.preview
            and Path(self.preview["path"]).suffix.lower() in MD.MARKDOWN
            and not getattr(self, "markdown_source", False)
        )

    def paint_markdown(self, text, y, x, height, width):
        width = max(12, width - 1)
        key = (text, width)
        if self.markdown_key != key:
            if self.markdown_future:
                self.markdown_future.cancel()
            self.markdown_key = key
            self.markdown_future = self.pool.submit(MD.render, text, width)
        if not self.markdown_future.done():
            self.ui.put(y, x, "Formatting Markdown…", curses.A_DIM)
            return
        try:
            lines = self.markdown_future.result()
        except (RuntimeError, OSError, ValueError, sp.SubprocessError) as exc:
            self.paint_text(
                "Formatting unavailable: " + str(exc) + "\n\n" + text,
                y,
                x,
                height,
                width,
            )
            self.markdown_visible = True
            return
        self.offset = min(max(0, self.offset), max(0, len(lines) - height))
        for i, line in enumerate(lines[self.offset : self.offset + height]):
            col = x
            for value, flags, color in line:
                style = self.ui.color(color) if color else 0
                for bit, attr in (
                    (MD.BOLD, curses.A_BOLD),
                    (MD.DIM, curses.A_DIM),
                    (MD.UNDERLINE, curses.A_UNDERLINE),
                    (MD.ITALIC, getattr(curses, "A_ITALIC", curses.A_UNDERLINE)),
                    (MD.STRIKE, getattr(curses, "A_STRIKEOUT", curses.A_DIM)),
                ):
                    if flags & bit:
                        style |= attr
                self.ui.put(y + i, col, value, style)
                col += MD.cells(value)
        self.markdown_visible = True

    def follow_document_link(self):
        if not self.preview:
            return
        links = MD.file_links(self.preview.get("text", ""), self.preview["path"])
        if not links:
            self.message = "No local document links in this file."
            return
        choice = self.choose(
            "Open linked file",
            [
                (str(i), label, path + ("#" + anchor if anchor else ""))
                for i, (label, path, anchor) in enumerate(links)
            ],
            "Open here · Back restores your place",
        )
        if choice is None:
            return
        _, path, anchor = links[int(choice)]
        try:
            document = self.busy(
                "Opening linked file…",
                lambda: self.b.data(self.row, "preview", path, "--mode", "docs"),
            )
        except (RuntimeError, OSError, ValueError, sp.SubprocessError) as exc:
            self.message = str(exc)
            return
        self.doc_history.append(
            (
                self.tab,
                self.preview,
                self.offset,
                self.folder,
                self.index,
                self.markdown_source,
            )
        )
        self.doc_history = self.doc_history[-30:]
        self.preview_request = None
        self.preview = document
        self.tab = "docs" if Path(path).suffix.lower() in DOCS else "files"
        self.folder = str(Path(path).parent) if str(Path(path).parent) != "." else ""
        self.selected_path = path
        self.preview_focus = True
        self.offset = 0
        self.markdown_source = False
        self.message = "Opened " + path
        if anchor:
            lines = self.busy(
                "Finding section…",
                lambda: MD.render(
                    document["text"],
                    max(
                        12,
                        self.s.getmaxyx()[1]
                        - (42 if self.s.getmaxyx()[1] >= 90 else 1)
                        - 1,
                    ),
                ),
            )
            import re

            for i, line in enumerate(lines):
                title = "".join(part[0] for part in line).strip().lower()
                slug = re.sub(r"[^\w -]", "", title).replace(" ", "-")
                if slug == anchor.lower():
                    self.offset = i
                    break

    def document_back(self):
        if not self.doc_history:
            self.message = "No previous document."
            return
        (
            self.tab,
            self.preview,
            self.offset,
            self.folder,
            self.index,
            self.markdown_source,
        ) = self.doc_history.pop()
        self.preview_request = None
        self.preview_focus = True
        self.message = "Returned to " + self.preview["path"]

    def browser(self, y, height, w):
        if self.preview:
            x = toolbar_start(w, ["l Links", "← Back"])
            x = self.button(y, x, "l Links", "doc-links")
            self.button(y, x, "← Back", "doc-back")
            y += 1
            height -= 1
        files = self.cache.get(self.tab, {}).get("files", [])
        changed = [r for r in files if r["changed"]]
        source = files if self.force_all or not changed else changed
        if self.preview and self.preview.get("request_id"):
            path = self.preview["path"]
            if not any(r["path"] == path for r in source):
                source = source + [dict(path=path, changed=False, status="  ")]
        self.rows = tree_rows(source, self.folder, self.query)
        self.index = max(0, min(self.index, len(self.rows) - 1))
        if self.selected_path:
            for i, (_, path, _) in enumerate(self.rows):
                if path == self.selected_path:
                    self.index = i
                    self.selected_path = None
                    break
        split = w >= 90
        left = min(40, max(25, w // 3)) if split else w
        if split or not self.preview_focus:
            start = max(0, min(self.index - height // 2, len(self.rows) - height))
            for i, (kind, path, row) in enumerate(
                self.rows[start : start + height], start
            ):
                text = (
                    (
                        "▸ "
                        if kind == "dir"
                        else "↰ " if kind == "up" else (row.get("status") or "  ") + " "
                    )
                    + (path if self.query else path.rsplit("/", 1)[-1])
                    + ("/" if kind == "dir" else "")
                )
                self.ui.put(
                    y + i - start,
                    1,
                    clipped(text, left - 2),
                    (
                        curses.A_REVERSE
                        if i == self.index and not self.preview_focus
                        else 0
                    ),
                )
                self.click_rows.append((y + i - start, 1, left, i))
            if not self.rows:
                self.ui.put(y, 1, "No files in this view.", curses.A_DIM)
        if split:
            for i in range(height):
                self.ui.put(y + i, left, "│", curses.A_DIM)
        if split or self.preview_focus:
            x = left + 2 if split else 1
            width = w - x
            text = (
                self.preview.get("text", "")
                if self.preview
                else "Select a file to read its contents."
            )
            if self.preview and self.preview.get("truncated"):
                text += "\n\n[Preview truncated at 512 KiB]"
            if self.preview:
                self.ui.put(y, x, self.preview["path"], curses.A_BOLD)
                y += 1
                height -= 1
            if self.formatted_markdown():
                self.paint_markdown(text, y, x, height, width)
            else:
                self.paint_text(text, y, x, height, width)

    def info_lines(self):
        d = self.cache.get("metadata", {})
        lines = []
        if self.tab == "usage":
            providers = self.cache.get("usage", {}).get("providers", [])
            for p in providers:
                name = p["provider"]
                lines.append(
                    (
                        name.upper()
                        + " · "
                        + ("Connected" if p.get("connected") else "Not connected"),
                        1,
                    )
                )
                quota = (
                    p.get("quota")
                    or (d.get("quota") if d.get("provider") == name else {})
                    or {}
                )
                found = False
                for key, q in quota.items():
                    if not isinstance(q, dict) or "used_percent" not in q:
                        continue
                    found = True
                    v = q.get("used_percent")
                    window = q.get("window_minutes")
                    label = (
                        "Weekly"
                        if window == 10080 or key == "seven_day"
                        else (
                            "5 hours"
                            if key == "five_hour"
                            else key.replace("_", " ").title()
                        )
                    )
                    lines += [
                        (
                            (
                                bar(v, 8) + f" {v:g}% · {label}"
                                if v is not None
                                else bar(None, 8) + " " + label
                            ),
                            level(v),
                        ),
                        (reset_note(q.get("resets_at")), 0),
                    ]
                if not found:
                    lines.append(
                        (
                            (
                                "Quota not reported"
                                if p.get("connected")
                                else "Sign in on the agent’s machine"
                            ),
                            0,
                        )
                    )
                if name == "claude":
                    left = self.cache.get("review", {}).get("remaining")
                    lines += [
                        (f'Review calls: {left if left is not None else "?"} / 2', 1),
                        ("24 turns · 20 min per call", 0),
                    ]
                lines.append(("", 0))
            if not providers:
                lines = [("Reading account limits…", 0)]
        elif self.tab == "context":
            x = d.get("context") or {}
            used = x.get("input")
            limit = x.get("window")
            pct = 100 * used / limit if used is not None and limit else None
            lines = [
                (d.get("model") or "Model not reported", 1),
                ("Reasoning: " + str(d.get("reasoning") or "not reported"), 0),
                (
                    bar(pct) + " " + (f"{pct:.0f}%" if pct is not None else "Unknown"),
                    level(pct),
                ),
                (f'Input {used if used is not None else "?"} / {limit or "?"}', 0),
                (
                    "Compactions: "
                    + str(
                        d.get("compactions")
                        if d.get("compactions") is not None
                        else "?"
                    ),
                    0,
                ),
                ("Last reported request; not a live estimate.", 0),
            ]
        elif self.tab == "services":
            d = self.cache.get("services", {})
            for s in d.get("services", []):
                used, limit, pct, capped = memory(s)
                up = int(s.get("UptimeSeconds") or 0)
                lines += [
                    (
                        s.get("Service", "container")
                        + " · "
                        + s.get("State", "unknown")
                        + " "
                        + s.get("Health", ""),
                        (
                            2
                            if s.get("State") == "running"
                            and s.get("Health") != "unhealthy"
                            else 4
                        ),
                    ),
                    (f'Up {up//86400}d {up%86400//3600}h · ↻ {s.get("Restarts",0)}', 0),
                    (bar(pct, 8) + " " + used + " / " + limit, level(pct)),
                    ("Container cap" if capped else "Shared Docker host limit", 0),
                    ("", 0),
                ]
            if not lines:
                lines = [("No containers running in this stream.", 0)]
        elif self.tab == "git-info":
            d = self.cache.get("git", {})
            lines = [(d.get("branch", ""), 1)] + [
                (r["status"] + " " + r["path"], 0) for r in d.get("files", [])
            ]
            if len(lines) == 1:
                lines.append(("Working tree clean", 2))
        return lines

    def render(self):
        self.markdown_visible = False
        self.s.erase()
        self.buttons = []
        self.click_rows = []
        h, w = self.s.getmaxyx()
        y = self.header()
        height = max(1, h - y - 2)
        if self.tab == "home":
            self.s.refresh()
            return
        if self.tab == "checkpoint":
            job = self.cache.get("checkpoint", {})
            marks = {"failed": "!", "done": "✓", "active": "…", "pending": "○"}
            text = "\n".join(
                marks[step["status"]] + " " + step["label"]
                for step in job.get("operation", {}).get("steps", [])
            )
            self.paint_text(
                text
                + "\n\n"
                + job.get("message", "No checkpoint requested yet.")
                + "\n\nStage reports show activity; only verification confirms the save.",
                y,
                1,
                height,
                w - 1,
            )
            self.s.refresh()
            return
        if self.tab in ("docs", "files", "git"):
            self.browser(y, height, w)
        elif self.tab == "docker":
            d = self.cache.get("docker", {})
            text = d.get("logs")
            if not text:
                text = (
                    "   __    __\n  /  \\__/  \\__\n  \\___________)\n\nNo container logs yet.\nR: start this stream’s Docker stack."
                    if d.get("state") in ("empty", "unprepared", "stopped")
                    else "Waiting for logs…"
                )
            self.paint_text(text, y, 1, height, w - 1, self.follow)
        elif self.tab == "tests":
            d = self.cache.get("tests", {})
            self.rows = d.get("results", [])
            if self.preview:
                self.paint_text(self.preview.get("text", ""), y, 1, height, w - 1)
            else:
                self.ui.put(
                    y,
                    1,
                    d.get("state", "Loading…")
                    + " · R: "
                    + ("Rerun tests" if d.get("configured") else "First tests run"),
                    self.ui.color(1),
                )
                self.index = max(0, min(self.index, len(self.rows) - 1))
                start = max(0, self.index - height + 3)
                for i, row in enumerate(self.rows[start : start + height - 2], start):
                    line, color = test_line(row)
                    self.ui.put(
                        y + 1 + i - start,
                        1,
                        line,
                        (curses.A_REVERSE if i == self.index else 0)
                        | self.ui.color(color),
                    )
                    self.click_rows.append((y + 1 + i - start, 1, w - 1, i))
                if not self.rows:
                    self.ui.put(
                        y + 2,
                        1,
                        d.get("message")
                        or "No results yet. First run uses project tooling.",
                        curses.A_DIM,
                    )
        elif self.tab == "review":
            d = self.cache.get("review", {})
            text = (
                self.preview.get("text", "")
                if self.preview
                else d.get("report_markdown")
                or d.get("reason")
                or d.get("title", "Loading review…")
            )
            c = self.cache.get("completion", {})
            summary = (
                "COMPLETION · "
                + c.get("state", "Loading…")
                + " · "
                + c.get("risk", "unassessed").upper()
                + "\n"
            )
            summary += c.get("scope", "") + "\n"
            summary += "\n".join(
                ("✓ " if x["status"] == "passed" else "○ ")
                + x["id"]
                + " · "
                + x["detail"]
                for x in c.get("checks", [])
            )
            summary += "\n" + "\n".join("Missing: " + x for x in c.get("missing", []))
            summary += "\n" + "\n".join(
                "Limitation: " + x for x in c.get("limitations", [])
            )
            self.paint_text(
                summary
                + "\nK: check completion · no tests / Claude\n\n"
                + str(d.get("remaining", "?"))
                + " / 2 Claude calls remain · R: review actions\n\n"
                + text,
                y,
                1,
                height,
                w - 1,
            )
        elif self.tab in ("agents", "questions"):
            rows = self.cache.get("agents", {}).get("agents", [])
            self.rows = (
                [r for r in rows if status(r) == "blocked"]
                if self.tab == "questions"
                else rows
            )
            self.index = max(0, min(self.index, len(self.rows) - 1))
            for i, r in enumerate(self.rows[: height // 2]):
                st = status(r)
                lead = (
                    self.cache.get("metadata")
                    if r["address"] == self.address.rsplit("/", 1)[-1]
                    else None
                )
                line = (
                    ("↳ " if r.get("parent") else "")
                    + W.label(r, "role", "agent")
                    + " · "
                    + W.label(r, "agent")
                    + " · "
                    + st
                )
                if lead:
                    line += (
                        " · "
                        + str(lead.get("model") or "?")
                        + " / "
                        + str(lead.get("reasoning") or "?")
                    )
                self.ui.put(
                    y + i * 2,
                    1,
                    line,
                    (curses.A_REVERSE if i == self.index else 0)
                    | self.ui.color(
                        3 if st in ("blocked", "done") else 2 if st == "working" else 1
                    ),
                )
                self.ui.put(y + i * 2 + 1, 2, r.get("title") or "", curses.A_DIM)
                self.click_rows.append((y + i * 2, 1, w - 1, i))
            if not self.rows:
                self.ui.put(
                    y,
                    1,
                    (
                        "No agent needs your input."
                        if self.tab == "questions"
                        else "Loading agents…"
                    ),
                    curses.A_DIM,
                )
        else:
            lines = self.info_lines()
            self.offset = max(0, min(self.offset, max(0, len(lines) - height)))
            for i, (text, col) in enumerate(lines[self.offset : self.offset + height]):
                self.ui.put(y + i, 1, text, self.ui.color(col) if col else 0)
        error = self.errors.get(self.tab) or self.errors.get(self.preview_request)
        footer = (
            error
            or self.message
            or (
                "Esc: return · r Refresh · h Helper · y Copy"
                if w >= 60
                else "Esc back · r refresh · h helper"
            )
        )
        self.ui.put(h - 1, 1, footer, self.ui.color(4) if error else curses.A_DIM)
        self.s.refresh()

    def open_selected(self):
        if not self.rows:
            return
        row = self.rows[self.index]
        if self.tab in ("docs", "files", "git"):
            kind, path, entry = row
            if kind in ("dir", "up"):
                self.folder = (
                    path
                    if kind == "dir"
                    else self.folder.rsplit("/", 1)[0] if "/" in self.folder else ""
                )
                self.index = 0
                return
            selected = dict(self.row)
            mode = self.tab
            self.preview = None
            self.preview_focus = True
            self.offset = 0
            self.errors.pop("preview", None)
            self.markdown_source = False
            self.preview_request = "preview:" + mode + ":" + path
            self.fetch(
                self.preview_request,
                lambda: self.b.data(selected, "preview", path, "--mode", mode),
                force=True,
            )
        elif self.tab == "tests":
            self.preview = dict(
                path=row["id"],
                text=json.dumps(row.get("argv"))
                + "\n\n"
                + row.get("tail", "No output"),
            )
            self.offset = 0
        elif self.tab in ("agents", "questions"):
            address = row["address"]
            on = W.machine(self.address)
            if on and "/" not in address:
                address = on + "/" + address
            self.dialog(lambda: self.ui.outside(lambda: self.b.attach(address)))

    def key(self, k):
        if k == curses.KEY_MOUSE:
            try:
                _, x, y, _, flags = curses.getmouse()
            except curses.error:
                return
            if flags & getattr(curses, "BUTTON4_PRESSED", 0):
                k = curses.KEY_UP
            elif flags & getattr(curses, "BUTTON5_PRESSED", 0):
                k = curses.KEY_DOWN
            elif flags & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                for yy, left, right, action in self.buttons:
                    if y == yy and left <= x < right:
                        return self.key_action(action)
                for yy, left, right, i in self.click_rows:
                    if y == yy and left <= x < right:
                        self.index = i
                        return self.open_selected()
                return
            else:
                return
        if k in ("\x1b", "q"):
            if self.preview or self.preview_focus:
                self.preview = None
                self.preview_request = None
                self.preview_focus = False
                self.offset = 0
                return
            if self.view == "info":
                return self.key_action("hide-info")
            return self.action("home")
        if k in ("\n", "\r", curses.KEY_ENTER):
            return self.open_selected()
        if k == curses.KEY_RESIZE:
            self.geometry = None
            return
        if k in (
            curses.KEY_UP,
            curses.KEY_DOWN,
            "j",
            "k",
            curses.KEY_NPAGE,
            curses.KEY_PPAGE,
            curses.KEY_HOME,
            curses.KEY_END,
        ):
            delta = (
                -1
                if k in (curses.KEY_UP, "k")
                else (
                    -max(1, self.s.getmaxyx()[0] - 7)
                    if k == curses.KEY_PPAGE
                    else (
                        max(1, self.s.getmaxyx()[0] - 7) if k == curses.KEY_NPAGE else 1
                    )
                )
            )
            listing = self.tab in (
                "docs",
                "files",
                "git",
                "tests",
                "agents",
                "questions",
            ) and not (self.preview_focus or (self.tab == "tests" and self.preview))
            if listing:
                self.index = max(
                    0,
                    min(
                        len(self.rows) - 1,
                        (
                            0
                            if k == curses.KEY_HOME
                            else (
                                len(self.rows) - 1
                                if k == curses.KEY_END
                                else self.index + delta
                            )
                        ),
                    ),
                )
            else:
                self.offset = (
                    0
                    if k == curses.KEY_HOME
                    else 10**9 if k == curses.KEY_END else max(0, self.offset + delta)
                )
                self.follow = k == curses.KEY_END
            return
        if k == "l" and self.tab in ("docs", "files"):
            return self.follow_document_link()
        if k in ("\b", "\x7f", curses.KEY_BACKSPACE) and self.tab in ("docs", "files"):
            return self.document_back()
        if k == "\t":
            self.preview_focus = not self.preview_focus
            return
        if (
            k == "v"
            and self.tab == "docs"
            and self.preview
            and Path(self.preview["path"]).suffix.lower() in MD.MARKDOWN
        ):
            self.markdown_source = not self.markdown_source
            self.offset = 0
            return
        if k == "r":
            self.last = {}
            self.errors = {}
            return
        if k == "x" and self.view == "info":
            return self.key_action("hide-info")
        if k == "p" and self.tab == "docker":
            self.frozen = not self.frozen
            self.message = "Frozen" if self.frozen else "Following live logs"
            return
        if k == "a" and self.tab in ("docs", "files"):
            self.force_all = not self.force_all
            self.folder = ""
            self.index = 0
            return
        if k == "/" and self.tab in ("docs", "files", "git"):
            value = self.dialog(lambda: self.ui.input("Filter files", self.query))
            if value is not None:
                self.query = value
                self.index = 0
            return
        if k == "h":
            return self.helper()
        if k == "y":
            return self.copy()
        if k == "K" and self.tab == "review":
            return self.check_completion()
        if k == "R":
            if self.tab == "tests":
                return self.run_tests()
            if self.tab == "review":
                return self.review_action()
            if self.tab == "docker" and self.confirm(
                "Start Docker?",
                W.label(self.row, "stream") + " · existing isolated stack",
            ):
                self.busy(
                    "Starting Docker…",
                    lambda: self.b.work(
                        self.row,
                        "docker",
                        "start",
                        W.label(self.row, "stream"),
                        "--json",
                    ),
                )
                self.last["docker"] = 0
            return
        if k in ("c", "m", "d", "b", "t", "a", "i", "s", "?"):
            return self.action(
                dict(
                    c="home",
                    m="menu",
                    d="docker",
                    b="browse",
                    t="checks",
                    a="actions",
                    i="info",
                    s="pick",
                    **{"?": "questions"},
                )[k]
            )

    def key_action(self, action):
        if action == "doc-links":
            return self.follow_document_link()
        if action == "doc-back":
            return self.document_back()
        if action == "refresh":
            self.last = {}
            return
        if action == "hide-info":
            self.close_requested = True
            return
        return self.action(action)

    def run(self):
        pane = os.environ["HERDR_PANE_ID"]
        native(
            "pane",
            "rename",
            pane,
            (
                "Information"
                if self.view == "info"
                else self.lane.title() + " · Stream controls"
            ),
        )
        try:
            while not self.close_requested:
                try:
                    self.sync()
                    self.fit()
                    self.render()
                    self.rendered()
                    try:
                        k = self.s.get_wch()
                    except curses.error:
                        continue
                    self.key(k)
                except (
                    RuntimeError,
                    OSError,
                    ValueError,
                    KeyError,
                    sp.SubprocessError,
                ) as e:
                    self.message = str(e)
                    self.errors[self.tab] = str(e)
        finally:
            self.pool.shutdown(wait=False)
        if self.view == "info":
            update(
                "layout",
                lambda x: dict(
                    x,
                    **{
                        self.lane: {
                            k: v for k, v in x[self.lane].items() if k != "info"
                        }
                    },
                ),
            )
            native("pane", "close", pane)


def start(lane, view):
    curses.wrapper(lambda s: Panel(s, lane, view).run())
