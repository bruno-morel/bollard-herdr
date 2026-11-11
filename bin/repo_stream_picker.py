"""Shared Studio/Work stream picker for Herdr TUI and ordinary terminals."""

import argparse
from repo_stream_backend import Backend, machine, label
from repo_terminal_ui import UI
import curses
import re
import subprocess as sp
import sys
import time

VALID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def slug(value):
    return re.sub("[^a-z0-9]+", "-", value.lower()).strip("-")


def source_tree(tree):
    if tree.get("stream") and not tree["primary"]:
        return dict(
            source="tree",
            stream=tree["stream"],
            folder=tree["folder"],
            checkout=tree["path"],
        )
    return dict(
        source="new",
        stream="",
        folder="",
        ref="refs/heads/" + tree["branch"] if tree["branch"] else None,
    )


def source_ref(ref):
    name = ref.get("stream") or slug(ref["branch"].split("/")[-1])
    return dict(
        source="recover" if ref.get("stream") else "new",
        stream=name,
        folder=name,
        ref=ref["ref"],
    )


def paired(names, field, value):
    out = dict(names, **{field: value, field + "Edited": True})
    other = "folder" if field == "stream" else "stream"
    if not names.get(other + "Edited"):
        out[other] = value
    return out


class Picker:
    def __init__(self, b, ui, args):
        self.b = b
        self.ui = ui
        self.on = args.machine or ""
        self.path = args.repo
        self.role = args.role
        self.data = None
        self.active = []
        self.rows = []
        self.machine_explicit = args.machine is not None
        self.select_only = getattr(args, "select_only", False)
        self.result = None
        self.current = getattr(args, "current", None)

    def refresh(self):
        self.active = self.b.inventory()
        if not self.machine_explicit and not self.data and self.active:
            self.on = machine(self.active[0]["address"])
        if self.path:
            path = self.path
            self.path = None
            self.data = self.b.catalog(self.on, path)

    def project(self):
        machines = self.b.hc("machine", "ls").get("machines", [])
        choices = [("", "⌂ This computer", "Repositories on this machine")] + [
            (m["name"], "▣ " + m["name"], m.get("state", ""))
            for m in machines
            if not m.get("temporary")
        ]
        on = self.ui.choose(
            "Repository · machine", choices, "Choose where the files live"
        )
        if on is None:
            return False
        listed = self.ui.busy(
            "Finding repository folders…", lambda: self.b.hc("ls", "--all")
        ).get("terminals", [])
        paths = list(
            dict.fromkeys(
                [
                    label(r, "checkout") or r.get("cwd")
                    for r in self.active
                    if machine(r["address"]) == on
                ]
                + [
                    r.get("cwd")
                    for r in reversed(listed)
                    if machine(r["address"]) == on
                ]
            )
        )

        def catalogs():
            result = {}
            for path in [p for p in paths if p][:12]:
                try:
                    d = self.b.catalog(on, path)
                    result[d["common"]] = d
                except (RuntimeError, OSError, ValueError, sp.SubprocessError):
                    continue
            return list(result.values())

        known = self.ui.busy("Finding repositories…", catalogs)
        options = [(d, d["repo"], d["primary"]) for d in known] + [
            (
                "path",
                "+ Choose another repository",
                "Enter an absolute folder path on this machine",
            )
        ]
        chosen = self.ui.choose("Repository", options, on or "This computer")
        if chosen is None:
            return False
        if chosen == "path":
            path = self.ui.input("Repository folder")
            if not path:
                return False
            chosen = self.ui.busy(
                "Reading Git metadata…", lambda: self.b.catalog(on, path)
            )
        self.on = on
        self.machine_explicit = True
        self.data = chosen
        return True

    def ensure_project(self):
        if self.data:
            return True
        rows = [r for r in self.active if machine(r["address"]) == self.on]
        if rows:
            self.data = self.ui.busy(
                "Reading repository…",
                lambda: self.b.catalog(
                    self.on, label(rows[0], "checkout") or rows[0]["cwd"]
                ),
            )
            return True
        return self.project()

    def attach(self, row):
        live = self.ui.busy("Checking conversation…", lambda: self.b.verify(row))
        self.deliver(live["address"])

    def deliver(self, address):
        if self.select_only:
            self.result = self.b.hc("get", address)
        else:
            self.ui.outside(lambda: self.b.attach(address))

    def branch(self, source):
        rows = [
            (r, r["label"], "Remote · last fetched" if r["remote"] else "Local branch")
            for r in self.data["refs"]
        ]
        chosen = self.ui.choose(
            "⑂ Branch",
            rows,
            "f Fetch latest remote references",
            keys={"f": "@fetch"},
            selected=next(
                (i for i, r in enumerate(rows) if r[0]["ref"] == source.get("ref")), 0
            ),
        )
        if chosen == "@fetch":
            self.data = self.ui.busy(
                "Fetching branches…",
                lambda: self.b.catalog(self.on, self.data["primary"], True),
            )
            return self.branch(source)
        return chosen

    def confirm(self, source):
        names = {"stream": source.get("stream", ""), "folder": source.get("folder", "")}
        agent = "codex"
        role = self.role
        advanced = False
        while True:
            self.ui.context = (self.on or "This computer") + " / " + self.data["repo"]
            isnew = source["source"] == "new"
            istree = source["source"] == "tree"
            rows = [
                (
                    "role",
                    "◉ " + role.title() + "  ▾",
                    "Studio: planning and handoffs · Work: implementation and Docker",
                ),
                (
                    "project",
                    "⌂ "
                    + (self.on or "This computer")
                    + " / "
                    + self.data["repo"]
                    + "  ▾",
                    "Change machine or repository",
                ),
                (
                    "source",
                    "▣ "
                    + {
                        "new": "New stream",
                        "tree": "Existing worktree",
                        "recover": "Existing branch",
                    }[source["source"]]
                    + "  ▾",
                    "New from main, an existing checkout, or a local/remote branch",
                ),
            ]
            if istree:
                rows += [
                    (
                        "source",
                        "Worktree  " + names["stream"] + "  ▾",
                        source["checkout"],
                    )
                ]
            else:
                rows += [
                    (
                        "branch",
                        "⑂ "
                        + str(source.get("ref") or "Choose base branch")
                        .replace("refs/remotes/", "")
                        .replace("refs/heads/", "")
                        + "  ▾",
                        "Committed source files only; fetch is available inside the branch picker",
                    )
                ]
                if isnew:
                    rows += [
                        (
                            "stream",
                            "Stream  " + (names["stream"] or "Choose a name…"),
                            "Branch and worktree folder follow this name",
                        )
                    ]
            rows += [
                (
                    "advanced",
                    "⚙ Customize  ▾" if not advanced else "⚙ Less customization  ▴",
                    "Agent and worktree folder override",
                )
            ]
            if advanced:
                rows += [
                    (
                        "agent",
                        "Agent   " + agent + "  ▾",
                        "Codex, Claude or Cursor; uses the selected account.",
                    )
                ]
                if not istree:
                    rows += [
                        (
                            "folder",
                            "Folder  " + (names["folder"] or "…"),
                            self.data["worktree_parent"] + "/" + names["folder"],
                        )
                    ]
            rows += [
                (
                    "open",
                    "▶ " + ("Create stream" if isnew else "Open " + names["stream"]),
                    "Creates or resumes only after choosing this row.",
                )
            ]
            action = self.ui.choose(
                "New conversation",
                rows,
                "e Existing conversation · Esc back",
                keys={"e": "@existing"},
            )
            if action is None or action == "@existing":
                return
            if action == "role":
                choice = self.ui.choose(
                    "Role",
                    [
                        ("studio", "◉ Studio", "Planning · docs · handoffs"),
                        ("work", "◆ Work", "Implementation · tests · Docker"),
                    ],
                    selected=0 if role == "studio" else 1,
                )
                if choice:
                    role = choice
            elif action == "project":
                if self.project():
                    source = dict(source="new", ref=self.data["default"])
                    names = {"stream": "", "folder": ""}
            elif action == "source":
                choice = self.ui.choose(
                    "Start from",
                    [
                        (
                            "new",
                            "+ New stream",
                            "Start from the repository default branch",
                        ),
                        ("tree", "▣ Existing worktree", "Reuse a registered checkout"),
                        ("ref", "⑂ Existing branch", "Recover local or remote streams"),
                    ],
                )
                if choice == "new":
                    source = dict(source="new", ref=self.data["default"])
                    names = {"stream": "", "folder": ""}
                elif choice == "tree":
                    tree = self.ui.choose(
                        "Worktree",
                        [
                            (
                                r,
                                r.get("stream") or r.get("branch") or "Detached",
                                r["path"],
                            )
                            for r in self.data["trees"]
                            if not r["primary"]
                        ],
                    )
                    if tree:
                        if not tree["available"]:
                            self.ui.message(
                                "Unavailable", "Restore this checkout first."
                            )
                            continue
                        source = source_tree(tree)
                        names = {k: source.get(k, "") for k in ("stream", "folder")}
                elif choice == "ref":
                    ref = self.branch(source)
                    if ref:
                        source = source_ref(ref)
                        names = {k: source.get(k, "") for k in ("stream", "folder")}
            elif action == "branch":
                ref = self.branch(source)
                if ref:
                    if source["source"] == "recover":
                        source = source_ref(ref)
                        names = {k: source.get(k, "") for k in ("stream", "folder")}
                    else:
                        source = dict(source, ref=ref["ref"])
            elif action == "advanced":
                advanced = not advanced
            elif action == "agent":
                choice = self.ui.choose(
                    "Agent",
                    [
                        ("codex", "Codex", "Uses your connected account"),
                        ("cursor", "Cursor", "Uses your connected account"),
                        ("claude", "Claude", "Uses your connected account"),
                    ],
                    selected=("codex", "cursor", "claude").index(agent),
                )
                if choice:
                    agent = choice
            elif action in ("stream", "folder"):
                text = self.ui.input(action.title() + " name", names[action])
                if text is not None:
                    if not VALID.fullmatch(text):
                        self.ui.message(
                            "Name needed", "Use lowercase words separated by hyphens."
                        )
                        continue
                    names = paired(names, action, text)
            elif action == "open":
                if not VALID.fullmatch(names["stream"]) or not VALID.fullmatch(
                    names["folder"]
                ):
                    self.ui.message("Name needed", "Choose a stream name first.")
                    continue
                if not istree and not source.get("ref"):
                    self.ui.message("Base needed", "Choose a branch first.")
                    continue
                retry = False
                while True:
                    try:
                        result = self.ui.busy(
                            "Preparing " + names["stream"] + "…",
                            lambda: self.b.prepare_and_open(
                                self.on,
                                self.data,
                                {
                                    **source,
                                    **{k: names[k] for k in ("stream", "folder")},
                                },
                                role,
                                agent,
                                lambda message: setattr(
                                    self.ui, "progress_text", message
                                ),
                                retry=retry,
                            ),
                        )
                        break
                    except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
                        curses.beep()
                        if (
                            self.ui.choose(
                                "Stream setup failed",
                                [
                                    (
                                        "retry",
                                        "Retry unfinished setup",
                                        "Keep the existing worktree and conversation",
                                    ),
                                    ("back", "Back", "Leave existing work intact"),
                                ],
                                str(e),
                            )
                            != "retry"
                        ):
                            return
                        retry = True
                self.role = role
                if result.get("address"):
                    self.deliver(result["address"])
                    return
                self.wait_setup(result)
                return

    def wait_setup(self, result):
        job = result["job"]
        on = result["on"]
        address = job.get("terminal")
        if address and on and "/" not in address:
            address = on + "/" + address
        # Opening uses the desktop controller. Observe it without sending prompts.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = self.ui.busy(
                "Opening " + result["stream"] + "…",
                lambda: self.b.script(
                    on,
                    result["role"],
                    ["flow", "status", result["stream"]],
                    cwd=result["cwd"],
                ),
            )
            if state.get("terminal") and state["terminal"] != job.get("terminal"):
                self.ui.message(
                    "Workflow changed",
                    "Another workflow now owns this stream. Choose its conversation from Active.",
                )
                return
            if state.get("state") == "ready" and state.get("lead"):
                lead = state["lead"]
                lead = (on + "/" + lead) if on and "/" not in lead else lead
                curses.beep()
                self.deliver(lead)
                return
            if state.get("state") not in ("queued", "preparing"):
                curses.beep()
                if (
                    state.get("state") == "needs-you"
                    and state.get("action") == "open"
                    and self.ui.choose(
                        "Setup needs attention",
                        [
                            (
                                "retry",
                                "Retry unfinished setup",
                                "Reuse checkout and any existing agent",
                            ),
                            ("back", "Back", "Keep the stream"),
                        ],
                        state.get("message", "Inspect the Workflow terminal."),
                    )
                    == "retry"
                ):
                    result["job"] = self.ui.busy(
                        "Retrying stream setup…",
                        lambda: self.b.script(
                            on,
                            result["role"],
                            [
                                "flow",
                                "open",
                                result["stream"],
                                "--retry-token",
                                state["token"],
                            ],
                            cwd=result["cwd"],
                        ),
                    )
                    return self.wait_setup(result)
                return
            self.ui.frame(
                "Opening " + result["stream"],
                state.get("message", "Preparing…"),
                "Esc returns to the picker; setup keeps running.",
            )
            self.ui.s.refresh()
            self.ui.s.timeout(1000)
            try:
                if self.ui.s.getch() == 27:
                    return
            finally:
                self.ui.s.timeout(-1)
        self.ui.message(
            "Setup still running",
            "The stream is preserved. Choose it from Active when ready. Workflow terminal: "
            + str(address),
        )

    def run(self):
        try:
            self.ui.busy("Loading streams…", self.refresh)
        except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
            self.ui.message("Could not load streams", str(e))
        selected = (
            next((r for r in self.active if r["address"] == self.current), None)
            or next(
                (
                    r
                    for r in self.active
                    if label(r, "role") == self.role
                    and (not self.data or label(r, "checkout") == self.data["root"])
                ),
                None,
            )
            or (self.active[0] if self.active else None)
        )
        while self.result is None:
            try:
                self.ui.context = (
                    (
                        selected.get("project_name", "")
                        + " / "
                        + label(selected, "stream")
                    )
                    if selected
                    else ""
                )
                rows = [
                    (
                        "pick",
                        "● "
                        + (
                            label(selected, "stream") + " · " + label(selected, "role")
                            if selected
                            else "Choose a conversation"
                        )
                        + "  ▾",
                        (
                            (machine(selected["address"]) or "This computer")
                            + " · "
                            + label(selected, "checkout")
                            if selected
                            else "Active streams from every connected machine"
                        ),
                    )
                ]
                if selected:
                    rows += [
                        (
                            "open",
                            "▶ Open conversation",
                            "Same process, role, model and saved prompt. No new agent.",
                        )
                    ]
                rows += [
                    (
                        "new",
                        "+ New conversation",
                        "Open an existing worktree or branch, or create a stream from main",
                    )
                ]
                chosen = self.ui.choose(
                    "Existing conversation",
                    rows,
                    "e Existing  ·  n New  ·  r Refresh",
                    keys={"e": "pick", "n": "new", "2": "new", "r": "refresh"},
                )
                if chosen is None:
                    return
                if chosen == "refresh":
                    self.ui.busy("Refreshing streams…", self.refresh)
                    selected = next(
                        (
                            r
                            for r in self.active
                            if selected and r["address"] == selected["address"]
                        ),
                        None,
                    )
                    continue
                if chosen == "pick":
                    picked = self.ui.choose(
                        "Active conversations",
                        [
                            (
                                r,
                                (r.get("project_name", "") + " / ")
                                + label(r, "stream")
                                + " · "
                                + label(r, "role"),
                                (machine(r["address"]) or "This computer")
                                + " · "
                                + label(r, "checkout"),
                            )
                            for r in self.active
                        ],
                        selected=next(
                            (
                                i
                                for i, r in enumerate(self.active)
                                if selected and r["address"] == selected["address"]
                            ),
                            0,
                        ),
                    )
                    if picked:
                        selected = picked
                elif chosen == "open":
                    self.attach(selected)
                elif chosen == "new":
                    if selected and not self.data:
                        self.on = machine(selected["address"])
                        self.data = self.ui.busy(
                            "Reading repository…",
                            lambda: self.b.catalog(
                                self.on, label(selected, "checkout")
                            ),
                        )
                    if self.ensure_project():
                        self.confirm(
                            dict(
                                source="new",
                                stream="",
                                folder="",
                                ref=self.data["default"],
                            )
                        )
            except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
                self.ui.message("Could not open stream", str(e))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--machine", help="Saved hc machine name; local for this computer")
    p.add_argument("--repo", help="Repository path on that machine")
    p.add_argument("--role", choices=("studio", "work"), default="studio")
    p.add_argument(
        "--ascii", action="store_true", help="Use plain characters instead of icons"
    )
    p.add_argument(
        "--actions", action="store_true", help="Open the existing workflow actions menu"
    )
    a = p.parse_args()
    a.machine = "" if a.machine == "local" else a.machine
    if not sys.stdin.isatty():
        p.error("Open this picker in an interactive terminal.")
    backend = Backend()

    def run(s):
        ui = UI(s, a.ascii)
        picker = Picker(backend, ui, a)
        if a.actions:
            if a.repo:
                ui.outside(lambda: backend.actions(a.machine or "", a.repo, a.role))
            elif picker.project():
                ui.outside(
                    lambda: backend.actions(picker.on, picker.data["primary"], a.role)
                )
        else:
            picker.run()

    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, ValueError, sp.SubprocessError, curses.error) as e:
        sys.exit("Streams: " + str(e))


if __name__ == "__main__":
    main()
