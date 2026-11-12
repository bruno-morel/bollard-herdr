#!/usr/bin/env python3
"""Disposable walkthrough smoke test. Real installers/Git; fake Herdr and agents.
Never connects to a server, starts an agent, or reads the user's Herdr state.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STUB = r"""
import json, os, sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=[a for a in sys.argv[1:] if a!='--json']
home=Path.home()
p=home/'fixture.json'
s=json.loads(p.read_text()) if p.exists() else {'terminals':[],'machines':[]}
def out(x): print(json.dumps(x))
def save(): p.write_text(json.dumps(s))
if name=='codex':
    assert args==['--help'], 'A real agent execution must never occur'
    print('--no-daemon'); sys.exit()
if name=='herdr-app':
    assert args[:2]==['do','layout.switch'], args
    app=Path(os.environ['HERDR_APP_HOME'])
    assert app==home/'.config/herdr-app'
    selected=json.loads(args[2])['name']
    assert (app/'layouts'/(selected+'.json')).is_file()
    s['layout']=selected;save();out({'ok':True});sys.exit()
if name=='herdr':
    assert args==['--version'], args
    print('fixture-terminal');sys.exit()
if name=='glow': sys.exit()
assert name=='hc', name
if args[:2]==['machine','add']:
    s['machines'].append(args[2]);save();out({'name':args[2]})
elif args[:2]==['machine','ls']:out({'machines':s['machines']})
elif args[0]=='ls':out({'terminals':s['terminals']})
elif args[0]=='get':
    out(next(r for r in s['terminals'] if args[1] in (r['address'],r['name'])))
elif args[0]=='run':
    assert '--keep' in args and '--bg' in args
    command=args[args.index('--')+1:]
    assert '_pane' in command and command[command.index('--mode')+1]=='new', command
    labels=dict(args[i+1].split('=',1) for i,a in enumerate(args) if a=='--label')
    s['terminals'].append(dict(address='t1',name=args[args.index('--name')+1],cwd=args[args.index('--cwd')+1],state='live',labels=labels,command=command))
    save();out(s['terminals'][-1])
elif args[0]=='keep': pass
elif args[0]=='label':
    row=next(r for r in s['terminals'] if r['address']==args[1])
    row['labels'].update(dict(x.split('=',1) for x in args[2:]));save()
else: raise AssertionError('Unexpected Herdr call: '+str(args))
"""


def main():
    with tempfile.TemporaryDirectory(prefix="bollard-walkthrough-") as temporary:
        base = Path(temporary).resolve()
        home = base / "home"
        home.mkdir()
        tools = base / "tools"
        tools.mkdir()
        for name in ("hc", "herdr-app", "herdr", "glow", "codex"):
            p = tools / name
            p.write_text("#!" + sys.executable + "\n" + STUB)
            p.chmod(0o755)
        # Do not inherit SSH agents, provider tokens, Herdr addresses or user config.
        env = dict(
            HOME=str(home),
            PATH=str(home / ".local/bin") + ":" + str(tools) + ":/usr/bin:/bin",
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_STATE_HOME=str(home / ".local/state"),
            XDG_CACHE_HOME=str(home / ".cache"),
            TMPDIR=str(base),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            PYTHONDONTWRITEBYTECODE="1",
            LC_ALL="en_US.UTF-8",
        )
        # Make Python available without including the user's executable directories.
        (tools / "python3").symlink_to(sys.executable)

        def run(*args, cwd=None, code=0):
            r = sp.run(
                args,
                cwd=cwd or base,
                env=env,
                text=True,
                capture_output=True,
                timeout=60,
            )
            if r.returncode != code:
                raise AssertionError(str(args) + "\n" + r.stdout + "\n" + r.stderr)
            return r.stdout

        source = base / "bollard-herdr"
        run("git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(source))
        # Exercise the working changes too, before they are committed.
        for raw in sp.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
        ).split(b"\0"):
            if not raw:
                continue
            rel = Path(os.fsdecode(raw))
            p = ROOT / rel
            if p.is_file():
                dest = source / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)

        def install(*args):
            return run("./install.sh", *args, cwd=source)

        (tools / "hc").rename(tools / "hc-not-on-path")
        try:
            missing = run("./install.sh", "all", "--check-deps", cwd=source, code=1)
            assert "[MISSING] hc" in missing and "core/install.sh" in missing
            run("./install.sh", "all", "--apply", cwd=source, code=1)
            assert not (
                home / ".local/bin"
            ).exists(), "Missing prerequisites still installed files"
        finally:
            (tools / "hc-not-on-path").rename(tools / "hc")
        output = install("all", "--check-deps")
        assert "[OK] hc" in output
        install("all")
        assert not (home / ".local/bin").exists(), "Preview wrote files"
        install("all", "--apply")
        install("all", "--verify")
        assert (
            json.loads((home / "fixture.json").read_text())["layout"]
            == "studio-work-portrait"
        )
        run("hc", "machine", "add", "tester@example.invalid")
        assert "tester@example.invalid" in run("hc", "machine", "ls")
        # A project needs an initial commit and a name/email before creating streams.
        project = base / "demo"
        run("git", "init", "-q", "-b", "main", str(project))
        run("git", "config", "user.name", "Walkthrough", cwd=project)
        run("git", "config", "user.email", "walkthrough@example.invalid", cwd=project)
        (project / "README.md").write_text("# Demo\n")
        run("git", "add", "README.md", cwd=project)
        run("git", "commit", "-qm", "Initial commit", cwd=project)
        catalog = json.loads(
            run(
                str(home / ".local/bin/repo-streams.py"),
                "catalog",
                "--repo",
                str(project),
            )
        )
        assert catalog["default"] == "refs/heads/main"
        # Both pickers prepare the selected base before opening the conversation.
        run(
            str(home / ".local/bin/repo-streams.py"),
            "prepare",
            "--repo",
            str(project),
            "--source",
            "new",
            "--stream",
            "first-stream",
            "--ref",
            catalog["default"],
        )
        run("studio", "herdr", "first-stream", "--agent", "codex", cwd=project)
        tree = base / "demo-worktrees/first-stream"
        assert (
            run("git", "branch", "--show-current", cwd=tree).strip()
            == "codex/first-stream"
        )
        assert (tree / "docs/handoffs/first-stream/context.md").is_file()
        assert (tree / "docs/REPO-WORKFLOW.md").is_file()
        assert (
            run("git", "check-ignore", "scratch/probe", cwd=tree).strip()
            == "scratch/probe"
        )
        run("studio", "herdr", "first-stream", cwd=project)
        # Herdr preparation must not initialize Zellij's global socket alias.
        assert not (base / ("zellij-" + str(os.getuid()))).exists()
        state = json.loads((home / "fixture.json").read_text())
        assert len(state["terminals"]) == 1, "Reopening duplicated the agent"
        assert state["terminals"][0]["labels"]["repo-tools.role"] == "studio"
        # A login shell with just the walkthrough snippet preserves normal arguments.
        snippet = "source " + str(source / "shell/herdr.zsh") + "; herdr --version"
        assert "fixture-terminal" in run("zsh", "-f", "-c", snippet)
        # Later installs preserve a user's different layout selection and private pins.
        state["layout"] = "personal-layout"
        (home / "fixture.json").write_text(json.dumps(state))
        pins = home / ".config/herdr-app/shared.json"
        pins.write_text('{"private":"keep"}')
        install("all", "--apply")
        assert (
            json.loads((home / "fixture.json").read_text())["layout"]
            == "personal-layout"
        )
        assert json.loads(pins.read_text()) == {"private": "keep"}
        install("all", "--apply", "--select-layout")
        assert (
            json.loads((home / "fixture.json").read_text())["layout"]
            == "studio-work-portrait"
        )
        print(
            "PASS: clean install, selected layout, connection command, real Git stream/handoff, reopen without duplication, shell shortcut, update preservation."
        )
        print(
            "BOUNDARIES: Herdr UI/core/SSH and agent launch are fixtures; no authentication, real agent, Docker or network installation was exercised."
        )


if __name__ == "__main__":
    main()
