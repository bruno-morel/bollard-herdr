"""Read-only refresh requests for terminal panels; no curses or workflow mutations."""

from functools import partial

from repo_stream_picker import label


def queries(backend, row, tab, *, panel=False, attached=False, frozen=False):
    """Return lazy (cache key, callable, interval) requests for one stream."""
    row = dict(row)
    stream = label(row, "stream")
    terminal = row["address"].rsplit("/", 1)[-1]
    result = [
        ("lead", partial(backend.hc, "get", row["address"]), 1 if attached else 5)
    ]

    def call(key, script, args, period):
        result.append((key, partial(backend.call, row, script, args), period))

    def work(key, *args, period=5):
        result.append((key, partial(backend.work, row, *args), period))

    if panel:
        call("checkpoint", "repo-new-conversation.py", [stream, "--status"], 3)
    if tab in ("docs", "files", "git"):
        result.append((tab, partial(backend.data, row, tab), 10))
    elif tab == "docker" and not frozen:

        def logs():
            value = backend.work(row, "observe", stream, "--json", "--status-only")
            if value.get("state") == "active":
                value.update(backend.call(row, "repo-logfeed.py", ["poll", stream]))
            return value

        result.append(("docker", logs, 2))
    elif tab == "tests":
        work(tab, "tests", "status", stream, "--json")
    elif tab == "review":
        work(tab, "review", stream, "--status", "--json")
        work("completion", "complete", stream, "--status", "--json", period=15)
    elif tab in ("agents", "questions"):
        result.append(("agents", partial(backend.data, row, "agents", terminal), 5))
    elif tab == "usage":
        call("usage", "repo-provider.py", ["status"], 30)
        work("review", "review", stream, "--status", "--json", period=30)
    elif tab == "services":
        work(tab, "observe", stream, "--json", "--status-only", "--metrics", period=15)
    elif tab == "git-info":
        result.append(("git", partial(backend.data, row, "git"), 10))
    if tab in ("agents", "questions", "context", "usage"):
        call("metadata", "repo-panel.py", ["metadata", terminal], 30)
    return result
