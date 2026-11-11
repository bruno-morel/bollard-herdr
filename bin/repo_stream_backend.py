"""Herdr transport and stream preparation; independent of terminal rendering."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import subprocess as sp


def machine(address):
    return address.rsplit("/", 1)[0] if "/" in address else ""


def label(row, key, default=""):
    return row.get("labels", {}).get("repo-tools." + key, default)


class Backend:
    def __init__(self):
        self.binary = shutil.which("hc") or str(Path.home() / ".local/bin/hc")

    def hc(self, *args):
        r = sp.run(
            [self.binary, args[0], "--json", *args[1:]],
            capture_output=True,
            text=True,
            timeout=35,
        )
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
        return json.loads(r.stdout)

    def script(self, on, name, args=(), cwd=None, timeout=25, raw=False):
        # Argument arrays end-to-end. Paths, refs and names never become shell text.
        code = (
            "import os,sys; from pathlib import Path; "
            'p=Path.home()/".local/bin"/sys.argv[1]; '
            'assert p.is_file(), "Studio/Work tools are not installed on this machine"; '
            'os.environ["PATH"]=os.pathsep.join([str(Path.home()/".local/bin"),'
            '"/opt/homebrew/bin","/usr/local/bin",os.environ.get("PATH","/usr/bin:/bin")]); '
            "os.execv(str(p), [str(p), *sys.argv[2:]])"
        )
        cmd = [
            self.binary,
            "exec",
            *(["--on", on] if on else []),
            "--timeout",
            str(timeout),
        ]
        if cwd:
            cmd += ["--cwd", cwd]
        r = sp.run(
            [*cmd, "--", "python3", "-c", code, name, *args],
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "Command failed")
        return r.stdout if raw else json.loads(r.stdout.strip().split("\n")[-1])

    def catalog(self, on, path, fetch=False):
        return self.script(
            on,
            "repo-streams.py",
            ["fetch" if fetch else "catalog", "--repo", path],
            timeout=120 if fetch else 25,
        )

    def describe(self, address):
        row = self.hc("get", address)
        if row.get("state") == "live" and label(row, "checkout"):
            try:
                row["project_name"] = self.catalog(
                    machine(address), label(row, "checkout")
                )["repo"]
            except (OSError, RuntimeError, ValueError, sp.SubprocessError):
                pass
        return row

    def inventory(self):
        rows = {}
        for role in ("studio", "work"):
            for r in self.hc("ls", "--label", "repo-tools.role=" + role).get(
                "terminals", []
            ):
                rows[r["address"]] = r
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(self.describe, a): a for a in rows}
            result = []
            for f in as_completed(jobs):
                try:
                    row = f.result()
                    if (
                        row.get("state") == "live"
                        and label(row, "role") in ("studio", "work")
                        and label(row, "stream")
                    ):
                        result.append(row)
                except (OSError, RuntimeError, ValueError, sp.SubprocessError):
                    pass  # A terminal may end between ls and get.
        return sorted(
            result,
            key=lambda r: (
                machine(r["address"]),
                label(r, "checkout"),
                label(r, "role"),
            ),
        )

    def verify(self, row):
        live = self.hc("get", row["address"])
        if live.get("state") != "live":
            raise RuntimeError(
                "This conversation ended. Select its worktree to reopen it."
            )
        data = self.catalog(
            machine(live["address"]), label(live, "checkout") or live["cwd"]
        )
        if (data.get("current") or {}).get("stream") != label(live, "stream"):
            raise RuntimeError(
                "The conversation checkout no longer matches its stream. Refresh before continuing."
            )
        live["project_name"] = data["repo"]
        return live

    def prepare_and_open(
        self, on, data, source, role, agent, progress=None, retry=False
    ):
        profile = role
        definition = (data.get("roles") or {}).get(profile, {})
        role = definition.get("base", role)
        progress = progress or (lambda message: None)
        progress("Checking existing conversation…")
        # Reuse live conversations before touching worktree setup or agent preferences.
        if source["source"] != "new":
            matches = []
            for row in self.inventory():
                if (
                    machine(row["address"]) == on
                    and label(row, "role") == role
                    and label(row, "stream") == source["stream"]
                ):
                    existing = self.catalog(on, label(row, "checkout") or row["cwd"])
                    if existing["common"] == data["common"]:
                        matches.append(row)
            if len(matches) > 1:
                raise RuntimeError(
                    "Multiple conversations match this stream. Choose one from Active."
                )
            if matches and (label(matches[0], "profile") or role) != profile:
                raise RuntimeError("Another role owns this workflow slot. Use Hand off to… first.")
            if matches:
                return {"address": self.verify(matches[0])["address"]}
        args = ["prepare", "--repo", data["primary"]]
        for k in ("source", "stream", "folder", "checkout", "ref"):
            if source.get(k):
                args += ["--" + k, source[k]]
        progress("Preparing worktree and handoff…")
        if retry:
            args.append("--retry")
        prepared = self.script(on, "repo-streams.py", args, timeout=120)
        progress("Starting agent / Docker setup…")
        job = self.script(
            on,
            role,
            ["flow", "open", source["stream"], "--role", role, "--agent", agent, "--profile", profile],
            cwd=prepared["cwd"],
            timeout=120,
        )
        return {
            "job": job,
            "cwd": prepared["cwd"],
            "stream": source["stream"],
            "role": role,
            "on": on,
        }

    def attach(self, address):
        if address == os.environ.get("HC_TERMINAL_ID"):
            return
        sp.run([self.binary, "attach", address], check=True)

    def actions(self, on, path, role):
        result = self.hc(
            "run",
            *(["--on", on] if on else []),
            "--bg",
            "--rm",
            "--no-parent",
            "--no-notify",
            "--cwd",
            path,
            "--",
            "python3",
            "-c",
            'import os,sys; from pathlib import Path; p=Path.home()/".local/bin/repo-flow.py"; os.execv(sys.executable,[sys.executable,str(p),sys.argv[1]])',
            role,
        )
        address = result.get("address") or result.get("terminal", {}).get("address")
        if not address:
            raise RuntimeError(
                "The workflow menu returned no address; inspect hc ls before retrying."
            )
        self.attach(address)
