# Standalone Herdr mods

Use Bollard's file browser or Docker logs in another Herdr desktop layout,
without adopting Studio/Work, its portrait layout, roles or review process.
Our full layout continues to use the same maintained panel code.

## Install

Prerequisites: Herdr desktop, Git and Python 3.9+; Docker Compose v2 for Docker.
The two small Python helpers must be available on the machine holding the files
and containers, including remote machines. They do not run agents or reviews.

Clone the public repository, then choose a package:

```sh
git clone https://github.com/bruno-morel/bollard-herdr.git
cd bollard-herdr
python3 install_mods.py files --apply
# Or: python3 install_mods.py docker --apply
# Or: python3 install_mods.py all --apply
```

Omit `--apply` to preview. `--verify` checks the installed files. The installer
copies only the selected mod and two Python helpers. It does **not** change
layouts, keyboard bindings, pinned streams or running conversations. It refuses
to overwrite an independently edited copy. Existing full Bollard users do not
need these optional mods for their current panels to keep working.

For SSH repositories, clone/pull the repository on the **remote host** too and run:

```sh
python3 install_mods.py all --host-only --apply
```

Ensure `~/.local/bin` is in PATH on that host. This installs only
`bollard-panel.py` and `repo_file_io.py`; no desktop, agents, Docker stacks or
worktrees are created. A missing helper will appear as a command-not-found error
in the panel: install it on the selected repository's host, not just the laptop.

## Open without replacing your layout

From a terminal on the **desktop computer**:

```sh
herdr-app do mod.open '{"name":"bollard-files"}'
herdr-app do mod.open '{"name":"bollard-docker"}'
```

These are explicit toggles: repeat to close. The installed mods use `place: none`
so installation itself does not add a panel to every window. For a persistent
panel in a custom layout, add a block using the relevant mod name. For example:

```json
{"id":"my-files","type":"block","content":{"mod":"bollard-files","props":{"mode":"docs"}},"size":{"weight":1}}
```

Follow the layout schema in your installed `~/.config/herdr-app/AGENTS.md` when
placing the block. You can optionally supply `props.context` with `cwd` and `on`
(`null` for this computer) to pin a repository; otherwise the panel follows the
active terminal/space. Keep the agent terminal as a separate block.

## File browser: Docs / Files / Git

- **Docs:** rendered Markdown and `.txt`, with source view and text editing.
- **Files:** all Git-tracked and untracked, non-ignored files; text preview/editing.
- **Git:** directory tree, actual diffs, staging and committing through Git.
- Changed files appear first when available; switch to all files, search, or use
  directory/type/list views. Each view retains its own selection.
- Saving checks the original file revision before replacing it. A changed file
  produces an error and keeps your draft instead of silently overwriting it.
- Standalone previews/editing support UTF-8 text up to 100 KB. Symlink traversal,
  binary files and `.git` internals are refused.

Bollard-specific helper, branch-sync and handoff actions stay in the full layout;
the standalone package does not silently install their workflow dependencies.

## Docker

The same scrollable log view includes copy logs, follow/latest, freeze, refresh,
startup feedback and the empty-state whale.

In a regular repository it uses a conventional Compose file at the Git root
(or current directory outside Git). Supported names are `compose.yaml`,
`compose.yml`, `docker-compose.yml`, `docker-compose.yaml`, plus the matching
conventional override file. Compose's project naming and `.env` handling apply.
Shell-inherited `COMPOSE_FILE`, `COMPOSE_PROJECT_NAME` and `COMPOSE_ENV_FILES` are
cleared so another stream's environment cannot select the wrong stack.

**Start Docker** explicitly runs `docker compose up -d`; it can create containers,
networks and volumes defined by that project. It does not generate Compose files,
start Docker Desktop, or force a rebuild. Custom multi-file Compose setups should
use the full workflow or a conventional override file.

Regular projects use bounded log snapshots every two seconds (up to 400 lines per
service, capped to 200,000 characters). Status refreshes every ten seconds. Freeze
stops display polling; containers continue running. Startup commands time out
after two minutes; inspect containers before retrying after a timeout.

If the selected terminal is an existing managed Bollard stream, Docker uses its
existing workflow backend and isolated Compose identity, including its persistent
log follower. It never falls back to the repository's default stack on a managed
stream error. Keep the full host tools installed for those streams.

## Updates and shared source

```sh
git pull --ff-only
python3 install_mods.py all --apply
python3 install_mods.py all --verify
```

Use the same selection you installed; use `--host-only` on a remote-only host.
For complete removal, close the mod and remove its `mods/bollard-files` or
`mods/bollard-docker` directory. Keep the two shared helpers if the other mod or
full Bollard installation uses them.

`packages/files/` and `packages/docker/` are generated distributions, with recipes
and Apache notices. Edit the maintained views in `herdr/mods/` and shared adapters
in `desktop/`, then run:

```sh
python3 desktop_build.py
python3 standalone_build.py
python3 tests/check_sources.py
```

Generation checks fail if packaged copies drift. The adapters isolate standalone
host access from workflow controls; renderers, file hierarchy, diff UI and Docker
log presentation are maintained once. Packaging alone does not submit these mods
to Herdr's gallery or change the full layout's screenshot.
