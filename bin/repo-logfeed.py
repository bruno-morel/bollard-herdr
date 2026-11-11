#!/usr/bin/env python3
"""A leased, bounded Docker log follower. Never starts/stops containers."""
import fcntl, hashlib, importlib.util, json, os, selectors, signal, subprocess as sp, sys, time, uuid
from repo_state import write_json as write
from pathlib import Path

BIN = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("observe", BIN / "repo-observe.py")
O = importlib.util.module_from_spec(spec)
spec.loader.exec_module(O)


def read(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def context(stream):
    root = Path(O.run(["git", "rev-parse", "--show-toplevel"], ".").strip()).resolve()
    if (
        not stream
        or O.run(["git", "symbolic-ref", "--short", "HEAD"], root).strip()
        != "codex/" + stream
    ):
        raise RuntimeError("Select the matching stream checkout")
    common = O.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], root
    ).strip()
    key = hashlib.sha256(os.fsencode(str(Path(common).resolve()))).hexdigest()[:16]
    state = (
        Path(
            os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))
        ).resolve()
        / "repo-tools/logs"
        / key
        / stream
    )
    for r in O.run(["git", "worktree", "list", "--porcelain"], root).splitlines():
        if r.startswith("worktree "):
            tree = Path(r[9:]).resolve()
            if tree == state or tree in state.parents:
                raise RuntimeError("Log runtime must be outside worktrees")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root, state, key


def poll(stream):
    root, state, key = context(stream)
    lease = state / "lease"
    lease.touch()
    with (state / "launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        status = read(state / "state.json")
        age = time.time() - status.get("heartbeat", 0)
        if age > 12 and (status.get("state") not in ("error", "ended") or age > 30):
            with (state / "worker.lock").open("a") as workerlock:
                try:
                    fcntl.flock(workerlock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return status
                info = O.inspect(stream, status_only=True)
                if info["state"] != "active":
                    return dict(info, state="idle")
                token = uuid.uuid4().hex[:10]
                status = dict(
                    state="starting",
                    logs="",
                    heartbeat=time.time(),
                    token=token,
                    project=info["project"],
                )
                write(state / "state.json", status)
                argv = [
                    "hc",
                    "run",
                    "--bg",
                    "--no-parent",
                    "--no-notify",
                    "--name",
                    "logs-" + key[:8] + "-" + token,
                    "--cwd",
                    str(root),
                    "--",
                    sys.executable,
                    str(BIN / "repo-logfeed.py"),
                    "_worker",
                    stream,
                    token,
                ]
                # Release for the worker to acquire; launch.lock still serializes callers.
                fcntl.flock(workerlock, fcntl.LOCK_UN)
                p = sp.run(argv, capture_output=True, text=True, timeout=10)
                if p.returncode:
                    raise RuntimeError(
                        "Log follower launch was not confirmed; refresh shortly."
                    )
        return status


def worker(stream, token):
    def stop(_signal, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    root, state, key = context(stream)
    proc = None
    buffer = b""
    with (state / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        status = read(state / "state.json")
        if status.get("token") != token:
            return
        sel = selectors.DefaultSelector()
        try:
            env = json.loads(O.run([str(BIN / "work"), "_herdr-env", stream], root))
            if not O.prepared_environment(env, root):
                raise RuntimeError("Docker stack has not been prepared")
            values = O.environment(env)
            proc = sp.Popen(
                [
                    "docker",
                    "compose",
                    "logs",
                    "--follow",
                    "--no-color",
                    "--timestamps",
                    "--tail",
                    "300",
                ],
                cwd=root,
                env=values,
                stdout=sp.PIPE,
                stderr=sp.STDOUT,
                start_new_session=True,
            )
            sel.register(proc.stdout, selectors.EVENT_READ)
            buffer = b""
            last = 0
            while time.time() - (state / "lease").stat().st_mtime < 45:
                for key, _ in sel.select(0.5):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if chunk:
                        buffer = (buffer + chunk)[-180000:]
                    else:
                        sel.unregister(key.fileobj)
                if time.time() - last >= 1:
                    status.update(
                        state="following",
                        logs="\n".join(
                            buffer.decode(errors="replace").splitlines()[-1800:]
                        ),
                        heartbeat=time.time(),
                    )
                    write(state / "state.json", status)
                    last = time.time()
                if proc.poll() is not None and not sel.get_map():
                    code = proc.returncode
                    status.update(
                        state="ended" if code == 0 else "error",
                        message=(
                            "Log follower ended. Refresh to reconnect."
                            if code == 0
                            else f"Docker logs exited with status {code}. See the log output."
                        ),
                        exit_code=code,
                        heartbeat=time.time(),
                    )
                    break
            else:
                status.update(
                    state="paused",
                    heartbeat=0,
                    message="Log follower paused while this pane was hidden.",
                )
        except SystemExit:
            status.update(state="paused", heartbeat=0, message="Log follower stopped.")
            raise
        except Exception as e:
            status.update(state="error", message=str(e), heartbeat=time.time())
        finally:
            if proc:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=3)
                except ProcessLookupError:
                    pass
                except sp.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
            if proc and proc.stdout:
                proc.stdout.close()
            status["logs"] = "\n".join(
                buffer.decode(errors="replace").splitlines()[-1800:]
            )
            sel.close()
            write(state / "state.json", status)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "_worker":
            worker(sys.argv[2], sys.argv[3])
        elif len(sys.argv) == 3 and sys.argv[1] == "poll":
            print(json.dumps(poll(sys.argv[2])))
        else:
            raise RuntimeError("usage: repo-logfeed.py poll <stream>")
    except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
        sys.exit("Docker logs: " + str(e))
