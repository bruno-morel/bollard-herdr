"""Pure TUI view data: no fetching, launching or state writes."""

import textwrap
from repo_terminal_ui import clean
from repo_tui_common import bar, level, memory, reset_note


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


def info_lines(tab, cache, errors=None):
    key = {"context": "metadata", "git-info": "git"}.get(tab, tab)
    if (errors or {}).get(key):
        return [("Could not refresh: " + errors[key], 4)]
    if key not in cache:
        return [("Loading…", 0)]
    d = cache.get("metadata", {})
    lines = []
    if tab == "usage":
        providers = cache.get("usage", {}).get("providers", [])
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
                left = cache.get("review", {}).get("remaining")
                lines += [
                    (f'Review calls: {left if left is not None else "?"} / 2', 1),
                    ("24 turns · 20 min per call", 0),
                ]
            lines.append(("", 0))
        if not providers:
            lines = [("Reading account limits…", 0)]
    elif tab == "context":
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
                    d.get("compactions") if d.get("compactions") is not None else "?"
                ),
                0,
            ),
            ("Last reported request; not a live estimate.", 0),
        ]
    elif tab == "services":
        d = cache.get("services", {})
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
    elif tab == "git-info":
        d = cache.get("git", {})
        lines = [(d.get("branch", ""), 1)] + [
            (r["status"] + " " + r["path"], 0) for r in d.get("files", [])
        ]
        if len(lines) == 1:
            lines.append(("Working tree clean", 2))
    return lines
