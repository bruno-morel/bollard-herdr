# Bollard for Herdr

Two streams. Keep the conversation; bring the tools to it.

![Codex and Claude stacked alongside a Cursor example stream](preview.png)

The preview shows three example conversations in this public repository, using
Codex, Claude and Cursor. No account credentials or private project content is shown.
The desktop starts with two unpinned streams. Planning above, coding below—or
pick any two conversations. No sheep. The agents wander enough already.

## Shape

```text
┌ Sidebar toggle · Add stream / window ─────────────────────┐
│ Optional sidebar │ Stream picker         Tools ▾ Actions ▾ │
│ Spaces + agents  │ ┌ Optional tools, above conversation ┐ │
│                  │ └────────────────────────────────────┘ │
│                  │ Conversation          │ Optional info  │
│                  ├───────────────────────┴────────────────┤
│                  │ Second stream: same independent layout │
└──────────────────┴────────────────────────────────────────┘
```

Keep conversation surfaces light in a light theme, tools subtly tinted and the
information panel contrasting. Use Herdr theme colors, native typography and
line icons. Right-align controls; give icon-only buttons tooltips. No CPU/network
meters. Narrow windows must keep controls reachable.

| Region | Content |
| --- | --- |
| Global bar | Sidebar toggle; add/split streams or open another window |
| Sidebar | Spaces grouped by repository/folder; agent notifications |
| Stream header | Repository/stream and state left; tools and Actions right |
| Conversation | Native agent terminal; stays separate from tools |
| Tools above | Conversation/Questions, Docker, Docs/Files/Git, Tests/Review |
| Optional right panel | Agent/model details, quota meters, Docker memory/status |

The source layout uses a 42px global bar, a hidden 168px sidebar and two resizable
lanes. Each lane has a header, a hidden tool stack, then conversation plus hidden
information panel (roughly one-quarter width, 210–430px).

## Behavior worth preserving

- **Choose a stream:** active conversation, existing worktree, remote branch or
  new branch. Studio/Work sets the role of a new agent; an existing agent keeps
  its identity and role. Opening a picker must not launch anything.
- **Docs / Files / Git:** folder, type or list browsing. Docs renders Markdown and
  text; Files browses everything; Git shows diffs. Prefer changed files. Agent
  file requests open here without replacing the conversation.
- **Docker:** scrollable, copyable live logs. No stack gets a friendly empty state
  and an explicit Start Docker action, not a wall of red.
- **Tests / Review:** project-native checks, bounded independent review (Claude default),
  and completion evidence. Displaying Review never spends allowance. Unknown or
  incomplete results must not become green.
- **Helpers:** separate read-only Codex/Claude/Cursor agents receive the current pane's
  context. They do not silently become the lead or spend the final-review attempt allowance.
- **New conversation:** save handoff → commit → push → restart. Show progress and
  failures. Retry rechecks identity and resumes the failed checkpoint.

Questions need attention; idle/finished agents get a subdued attention color;
errors are red. Missing model, reasoning or quota data stays unknown.
Each lane owns its machine/repository/stream selection. Never use a shared mutable
selection for both lanes or claim the same agent with two launchers.

## Install

This layout needs Bollard's controllers; copying the pictures won't do it.
After the [prerequisites](../docs/setup.md#prerequisites), from this repo:

```sh
./install.sh desktop --check-deps # install missing prerequisites first, including hc
./install.sh desktop --apply   # desktop machine
./install.sh tui --check-deps   # run on the remote host too
./install.sh tui --apply       # remote development host, from its own clone
```

Choose **studio-work-portrait** in Herdr, then choose your streams.
Use `all` instead of `desktop` to install the laptop TUI too. Desktop and TUI share
controllers, conversations and evidence; this recipe describes the desktop.
Credentials and runtime state stay outside Git. macOS is tested; other platforms
are unverified.

## Building blocks

`layouts/studio-work-portrait.json` defines the lanes. `repo-portrait` owns the
manager, headers, conversation placeholders and information panels. Reader,
changes and review mods render tools. Picker, workflow, helper, sync, spaces,
folders, tabs and menu mods provide controls. `helpers/window.py` opens windows.
The `agents` and `workspace-chrome` mods come from Herdr itself.

Use native `gpui-kit`/`gpui-base` views and Herdr APIs, not DOM components.
Shared sources live in `../desktop/shared/`; `python3 desktop_build.py` generates
self-contained mod copies. Herdr checks each mod in isolation.

## Verify

Follow the [development checks](../docs/development.md#check-a-change), then try:

1. Clean launch: two empty streams, no errors or accidental agents.
2. Reopen a conversation: same identity; tools stay in their own lane.
3. Open a file, scroll/copy logs, inspect failed tests and missing authentication.
4. Inspect Review: no Claude call. Exercise checkpoint failure/retry safely.

Native checks alone don't exercise dropdowns or deferred actions. Preserve
personal pins during upgrades, and keep terminal IDs out of published layouts.
