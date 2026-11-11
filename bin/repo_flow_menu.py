"""Interactive workflow menu. Dispatch decisions belong to the controller."""

from pathlib import Path
import subprocess as sp
import sys
import repo_helper_context as C

BIN = Path(__file__).resolve().parent


def run_menu(role, dispatch):
    if not sys.stdin.isatty():
        raise RuntimeError("Use a subcommand or --help outside an interactive terminal")
    while True:
        print(
            "\nStudio / Work\n  1 Plan / open Studio\n  2 Open Work\n  3 Prepare implementation\n  4 Implement through review\n  5 Add research helper\n  h Ask a helper about pane evidence\n  6 Add coding helper\n  7 Status\n  8 Attach to a terminal\n  9 Pause workflow\n  t Tests (status / rerun)\n  q Back"
        )
        choice = input("Choice: ").strip()
        if choice in ("", "q"):
            return
        if choice in ("1", "2"):
            sp.run(
                [
                    str(BIN / "repo-workflow"),
                    "--machine",
                    "local",
                    "--repo",
                    str(Path.cwd()),
                    "--role",
                    "studio" if choice == "1" else "work",
                ]
            )
            continue
        if choice == "8":
            sp.run(["hc", "attach"])
            continue
        if choice == "h":
            stream = input("Stream (Enter for current): ").strip()
            choices = list(C.PRESETS)
            for i, preset in enumerate(choices, 1):
                print(str(i) + " " + C.PRESETS[preset][0])
            n = input("Preset [1]: ").strip() or "1"
            if not n.isdecimal() or not 1 <= int(n) <= len(choices):
                continue
            preset = choices[int(n) - 1]
            file = input("Pane context JSON file: ").strip()
            agent = input("Agent codex / claude / cursor [codex]: ").strip() or "codex"
            argv = (
                [role, "helper"]
                + ([stream] if stream else [])
                + [
                    "--preset",
                    preset,
                    "--context-file",
                    file,
                    "--agent",
                    agent,
                    "--role",
                    role,
                ]
            )
            if preset == "campaign-follow-up":
                argv += [
                    "--period",
                    input("Dates YYYY-MM-DD..YYYY-MM-DD: ").strip(),
                    "--compare-period",
                    input("Comparison dates: ").strip(),
                ]
            question = input("Question (Enter for preset): ").strip()
            if question:
                argv += ["--scope", question]
            try:
                dispatch(argv + ["--preview"])
                if input("Start this read-only helper? [y/N] ").strip().lower() == "y":
                    dispatch(argv)
            except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
                print(str(e))
            continue
        if choice == "t":
            stream = input("Stream (Enter for current): ").strip()
            action = input("Tests: first / run / status [status]: ").strip() or "status"
            if action not in ("status", "run", "first"):
                continue
            extra = []
            if action == "first":
                target = input(
                    "Lead terminal for test child (e.g. t18; Enter if already configured): "
                ).strip()
                if target:
                    extra = [
                        "--target",
                        target,
                        "--agent",
                        input("Child agent codex / claude / cursor [codex]: ").strip()
                        or "codex",
                    ]
            sp.run(
                [
                    str(BIN / "work"),
                    "tests",
                    action,
                    *([stream] if stream else []),
                    *extra,
                    "--json",
                ]
            )
            continue
        action = {
            "3": "prepare",
            "4": "implement",
            "5": "helper",
            "6": "helper",
            "7": "status",
            "9": "pause",
        }.get(choice)
        if not action:
            continue
        stream = input("Stream (Enter for current): ").strip()
        argv = ["work", action] + ([stream] if stream else [])
        if action in ("helper", "implement"):
            argv += [
                "--agent",
                input("Agent codex / claude / cursor [codex]: ").strip() or "codex",
            ]
        if action == "implement":
            argv += [
                "--reviewer",
                input("Independent reviewer [claude]: ").strip() or "claude",
            ]
        if action == "helper":
            argv += [
                "--kind",
                "research" if choice == "5" else "code",
                "--role",
                role,
                "--scope",
                input("Focused helper task: ").strip(),
            ]
        try:
            dispatch(argv)
        except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
            print(str(e))
