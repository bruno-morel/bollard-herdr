#!/usr/bin/env python3
"""Git-backed stream picker. Catalog is read-only; prepare never resets an existing checkout."""
import argparse, fcntl, hashlib, json, os, re, subprocess as sp, sys
from pathlib import Path

BIN = Path(__file__).resolve().parent
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def fail(message):
    raise RuntimeError(message)


def git(root, *args, check=True, timeout=15):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if "GIT_SSH_COMMAND" not in env and "GIT_SSH" not in env:
        env["GIT_SSH_COMMAND"] = (
            "ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1"
        )
    p = sp.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    if check and p.returncode:
        fail(p.stderr.strip() or "Git command failed")
    return p


def catalog(path):
    inside = git(path, "rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode or inside.stdout.strip() != "true":
        fail("Choose a directory inside a Git-controlled source tree.")
    root = Path(git(path, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    common = Path(git(root, "rev-parse", "--git-common-dir").stdout.strip())
    common = (root / common).resolve()
    trees = []
    for record in git(root, "worktree", "list", "--porcelain", "-z").stdout.split(
        "\0\0"
    ):
        f = dict(
            x.split(" ", 1) if " " in x else (x, "") for x in record.split("\0") if x
        )
        if "worktree" not in f:
            continue
        branch = f.get("branch", "").removeprefix("refs/heads/")
        name = (
            branch[6:]
            if branch.startswith("codex/") and SLUG.fullmatch(branch[6:])
            else None
        )
        tree = Path(f["worktree"])
        trees.append(
            dict(
                path=str(tree),
                branch=branch,
                stream=name,
                available=tree.is_dir(),
                primary=not trees,
                locked="locked" in f,
                folder=tree.name,
            )
        )
    if not trees or not trees[0]["available"]:
        fail("The primary repository checkout is unavailable.")
    primary = trees[0]["path"]
    refs = []
    remotes = git(root, "remote").stdout.splitlines()
    raw = git(
        root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)%00%(symref)",
        "refs/heads/",
        "refs/remotes/",
    ).stdout
    for line in raw.splitlines():
        ref, oid, sym = line.split("\0")
        if sym:
            continue
        remote = ref.startswith("refs/remotes/")
        label = ref.removeprefix("refs/remotes/").removeprefix("refs/heads/")
        remote_name = (
            next(
                (
                    r
                    for r in sorted(remotes, key=len, reverse=True)
                    if label.startswith(r + "/")
                ),
                None,
            )
            if remote
            else None
        )
        branch = label[len(remote_name) + 1 :] if remote_name else label
        stream = (
            branch[6:]
            if branch.startswith("codex/") and SLUG.fullmatch(branch[6:])
            else None
        )
        refs.append(
            dict(
                ref=ref,
                label=label,
                branch=branch,
                remote=remote,
                stream=stream,
                oid=oid,
            )
        )
    names = {r["ref"] for r in refs}
    default = None
    for remote in sorted(remotes, key=lambda r: r != "origin"):
        head = git(
            root,
            "symbolic-ref",
            "--quiet",
            "refs/remotes/" + remote + "/HEAD",
            check=False,
        ).stdout.strip()
        if head in names:
            default = head
            break
    if not default:
        default = next(
            (
                r
                for r in [
                    "refs/remotes/origin/main",
                    "refs/heads/main",
                    "refs/remotes/origin/master",
                    "refs/heads/master",
                ]
                if r in names
            ),
            None,
        )
    return dict(
        root=str(root),
        primary=primary,
        common=str(common),
        repo=Path(primary).name,
        worktree_parent=primary + "-worktrees",
        default=default,
        trees=trees,
        refs=refs,
        remotes=remotes,
        current=next(
            (t for t in trees if t["available"] and os.path.samefile(t["path"], root)),
            None,
        ),
    )


def prepare(path, source, stream, folder=None, ref=None, checkout=None, retry=False):
    if not SLUG.fullmatch(stream):
        fail("Use lowercase words separated by hyphens for the stream name.")
    folder = folder or stream
    if not SLUG.fullmatch(folder):
        fail("Use lowercase words separated by hyphens for the worktree folder name.")
    if not (BIN / "work").is_file():
        fail(
            "Studio/Work tools are not installed on this machine. Choose JumpBox, or install the workflow tools here first."
        )
    initial = catalog(path)
    runtime = (
        Path(
            os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))
        ).resolve()
        / "repo-tools"
    )
    if any(
        Path(t["path"]).resolve() == runtime
        or Path(t["path"]).resolve() in runtime.parents
        for t in initial["trees"]
    ):
        fail("Runtime state must be outside all worktrees.")
    runtime.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.fsencode(initial["common"])).hexdigest()[:16]
    with (runtime / ("picker-" + key + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = catalog(path)
        root = data["primary"]
        branch = "codex/" + stream
        local = "refs/heads/" + branch
        refs = {r["ref"]: r for r in data["refs"]}
        matches = [t for t in data["trees"] if t["branch"] == branch]
        target = None
        if retry and source == "new" and matches:
            expected = (Path(data["worktree_parent"]) / folder).resolve()
            if (
                len(matches) != 1
                or Path(matches[0]["path"]).resolve() != expected
                or not matches[0]["available"]
            ):
                fail(
                    "Retry checkout differs from the requested destination. Inspect Worktrees; no files changed."
                )
            source = "tree"
            checkout = matches[0]["path"]
        if source == "tree":
            target = next(
                (
                    t
                    for t in data["trees"]
                    if checkout
                    and Path(t["path"]).resolve() == Path(checkout).resolve()
                ),
                None,
            )
            if not target or not target["available"]:
                fail("That worktree is no longer available. Refresh the list.")
            if target["primary"]:
                fail(
                    "Use the primary checkout as the base for a new stream; it is not a managed stream worktree."
                )
            if target["stream"] != stream:
                fail(
                    "An existing worktree keeps its branch and stream name. Choose a new stream to branch from it."
                )
        else:
            selected = refs.get(ref or data["default"])
            if not selected:
                fail(
                    "That base branch is unavailable. Refresh branches and choose an existing branch."
                )
            ref = selected["ref"]
            if source == "recover":
                if selected["stream"] != stream:
                    fail(
                        "Recovery keeps the branch name. Choose New from branch to use another name."
                    )
                if matches:
                    target = matches[0]
                elif local in refs and selected["remote"]:
                    # Preserve local commits; recovering a remote must not replace them.
                    ref = local
            elif source == "new":
                if local in refs or any(r["stream"] == stream for r in refs.values()):
                    fail(
                        "This stream already exists locally or on a known remote. Select it from Worktrees or Branches to resume it."
                    )
            else:
                fail(
                    "Choose an existing worktree, a branch to recover, or a new stream."
                )
            if target and (target["primary"] or not target["available"]):
                fail(
                    "That branch has an unavailable or primary checkout; restore it before continuing."
                )
            if not target:
                parent = Path(data["worktree_parent"])
                if parent.is_symlink():
                    fail("The worktree parent must not be a symlink.")
                if (
                    git(
                        parent.parent, "rev-parse", "--is-inside-work-tree", check=False
                    ).stdout.strip()
                    == "true"
                ):
                    fail("The worktree parent is inside another repository.")
                destination = parent / folder
                if destination.exists() or destination.is_symlink():
                    fail(
                        "The destination folder already exists; choose its registered worktree or another folder name."
                    )
                if any(
                    Path(t["path"]).resolve() == destination.resolve()
                    for t in data["trees"]
                ):
                    fail(
                        "Git already registers this destination. Restore that checkout first."
                    )
                parent.mkdir(parents=True, exist_ok=True)
                if source == "recover" and ref == local:
                    git(root, "worktree", "add", str(destination), branch)
                else:
                    git(
                        root,
                        "worktree",
                        "add",
                        (
                            "--track"
                            if source == "recover" and refs[ref]["remote"]
                            else "--no-track"
                        ),
                        "-b",
                        branch,
                        str(destination),
                        ref,
                    )
                target = dict(path=str(destination), branch=branch, stream=stream)
        # Keep original port allocation, environment source, Docker and recovery behavior.
        p = sp.run(
            [str(BIN / "work"), "prepare", stream],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if p.returncode:
            fail(
                (p.stderr.strip() or p.stdout.strip())
                + " The checkout is preserved; no files were reset."
            )
        return dict(
            cwd=root,
            checkout=target["path"],
            stream=stream,
            repo=data["repo"],
            branch=branch,
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["catalog", "fetch", "prepare"])
    p.add_argument("--repo", default=".")
    p.add_argument("--source", choices=["tree", "recover", "new"])
    p.add_argument("--stream")
    p.add_argument("--folder")
    p.add_argument("--ref")
    p.add_argument("--checkout")
    p.add_argument(
        "--retry",
        action="store_true",
        help="Reuse the exact requested worktree after a partial preparation",
    )
    a = p.parse_args()
    if a.action == "prepare":
        if not a.stream or not a.source:
            p.error("prepare requires --source and --stream")
        out = prepare(a.repo, a.source, a.stream, a.folder, a.ref, a.checkout, a.retry)
    else:
        out = catalog(a.repo)
        if a.action == "fetch":
            for remote in out["remotes"]:
                git(out["primary"], "fetch", remote, timeout=30)
            out = catalog(a.repo)
    print(json.dumps(out))


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, RuntimeError, sp.SubprocessError) as e:
        sys.exit("Streams: " + str(e))
