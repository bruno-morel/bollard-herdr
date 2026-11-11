# Bollard for Herdr

Repository-aware planning, implementation and review across Herdr desktop,
terminal and phone sessions. Keep the agent conversation separate from files,
logs, tests and review, while Studio and Work share the same Git stream.

This is a personal workflow published for reuse, not an official Herdr product.
Currently exercised on macOS Apple Silicon (laptop) and Intel (remote host).
Linux portability is not yet verified. Windows is not supported.

## What is included

- `studio`: planning, product/marketing documents and handoffs.
- `work`: implementation, isolated Docker stacks, tests and bounded independent review.
- Herdr desktop mods: two portrait streams, file trees, Markdown, Git changes,
  Docker logs, test results, review/completion evidence, helpers and usage panels.
- Herdr terminal dashboard: the same core conversations, compact phone views,
  rendered Markdown, relative document links and back navigation.
- Checkpoint/retry flows for saving context, committing, pushing and starting a
  fresh conversation in the same stream.
- Zellij layouts for the existing alternative workflow.

Persistent project context belongs in the project's `docs/`; temporary assets
belong in ignored `scratch/`. Credentials, conversation history, allowance
counters, stream pins and machine connections stay outside this repository.

## Prerequisites

Install Git, Python 3.9+, zsh, SSH, Herdr desktop
(`herdr-app`), Herdr terminal (`herdr`), and herdr-core (`hc`). Install and sign
in to the agents you use: Codex, Claude Code and/or Cursor CLI. Glow provides
terminal Markdown rendering. Docker with Compose is needed for Work stacks;
Zellij and lazygit are needed only for the Zellij interface.

Use the upstream installation instructions at https://herdr.dev/.
No vendor binaries, generated Herdr SDK declarations, or login credentials are
bundled. Herdr mods use native GPUI APIs and may need updates as Herdr evolves.
The original sidebar components were adapted from Herdr desktop 0.1.13.

## Quick install choices

After cloning, choose one:

```sh
./install.sh desktop --apply  # shared workflows + desktop UI
./install.sh tui --apply      # shared workflows + terminal/phone UI
./install.sh all --apply      # both interfaces on this machine
```

Omit `--apply` for a preview. `laptop` remains an alias for both interfaces;
`jumpbox` remains the remote/TUI profile. No agent is started by installation.
Shared CLI support is installed with either interface. The desktop assets live
under `herdr/`; TUI presentation modules/config live under `bin/repo_tui*` and
`tui/`. They share the backend, not separate copies of conversations or rules.
No shell profile, login, remote connection, or private stream selection is
silently configured. See `shell/herdr.zsh` for the optional terminal default.

## Install

Clone this repository on each machine:

```sh
git clone https://github.com/bruno-morel/bollard-herdr.git
cd bollard-herdr
python3 install.py laptop             # preview
python3 install.py laptop --apply     # desktop + CLI/TUI + Zellij
```

On the remote development host use `jumpbox` instead of `laptop`. It installs
CLI/TUI and Zellij support without requiring the desktop app. Ensure
`$HOME/.local/bin` is on PATH on both machines, including remote SSH commands.

The installer refuses unrecognized edits to installed files. Reconcile those
into this checkout before updating; there is no blanket overwrite switch.
Existing desktop layouts are preserved because they contain personal stream
pins. Fresh installations receive an unpinned layout. Existing custom windows
receive the maintained mods, while their window/layout state is preserved.

Select **studio-work-portrait** in Herdr desktop's layout picker. Connect your
remote machine through Herdr and pick your streams. Use `repo-tui` for the
terminal dashboard. To make plain `herdr` open it, source the absolute path to
`shell/herdr.zsh` from `~/.zshrc`; explicit Herdr arguments still pass through.
This shell preference is opt-in; the installer does not edit your shell profile.

## Update either machine

```sh
python3 sync.py laptop
# On the remote host:
python3 sync.py jumpbox
```

This requires a clean source checkout, pulls with `--ff-only`, installs and
verifies. It does not restart agents, reset conversations, recreate worktrees,
reset review allowances, or replace personal desktop pins. Existing TUI
processes load updated Python code when reopened. Commit and push intentional
source changes before updating the other machine.

## Workflow

From inside a Git checkout, use the Herdr stream picker or:

```sh
studio herdr my-feature
studio handoff
work herdr my-feature
```

Use the interface's Prepare implementation and Implement → Review actions for
the guided workflow. The initial role prompt, handoff and risk-based evidence
rules are maintained in `bin/`. A successful test run is not a claim that all
possible bugs are excluded. Independent Claude review is deliberate and bounded;
opening the interface does not start a review or spend an agent allowance.

Review/checkpoint/cleanup commands can mutate Git, Docker or remote state when
requested. Inspect command help before using them. In particular, checkpoint
may commit and push the current stream, and force removal may delete local
worktree changes and Docker volumes.

The `work-tenhumans` and `tenhumans` layouts retain optional application-specific
service names for compatibility. The generic `work` layout and Git-root
selection do not assume those project names or directories.

## Development and validation

Edit sources here, not deployed copies. `install.py` installs atomically and
records hashes outside the repository to detect drift on the next update.

```sh
brew install glow  # real Markdown rendering tests use Glow
python3 tests/run.py
python3 tests/check_sources.py
python3 install.py laptop --verify
herdr-app check herdr/mods/repo-portrait
```

The unit/integration suite uses temporary Git repositories and mocked agent
controllers. It does not call a paid agent, push your project branches, or run
your product's tests. Native Herdr checks require the app runtime and a desktop
session; they supplement the portable checks.

## Layout of this repository

| Directory | Contents |
| --- | --- |
| `bin/` | Shared launchers, helpers and workflow controllers |
| `herdr/` | Custom desktop mods, layout templates and window helper |
| `tui/`, `shell/` | Terminal configuration and optional default command |
| `zellij/` | Alternative terminal layouts |
| `tests/` | Controller, installer and source checks |

Apache-2.0. See LICENSE, NOTICE and THIRD_PARTY_NOTICES.md.
