# Cleanup audit

**Completed: 2026-11-11.** Keep the checks; lose the ceremony.

## What changed and how we checked it

| Area | Evidence |
| --- | --- |
| Dead paths | Removed obsolete shell handlers, duplicate setup and unused imports. |
| Shared logic | Desktop helpers, check validation, transport, presets, CLI help, atomic JSON writes, Compose validation. |
| Boundaries | Picker, transport, terminal input, menu, display rows and refresh queries live outside workflow controllers. |
| Workflow tests | Stream identity, checkpoint retries, completion evidence, bounded review, helper ownership and ambiguous task delivery. |
| Git tests | Real disposable repos: merge previews, stale tokens, ignored files and conflicts. |
| Failure tests | Installer rollback, interrupted writes, Docker ownership, stream-switch races, transfer/recovery failures, quota refresh, worktree removal and rejected remote-deletion retries. |
| TUI | Real pseudo-terminal: phone/desktop resizing, conversation picker, changed-file folders, Markdown paging and Docker log scrolling. |
| Docs | Short guides, diagrams, checked relative links, installer profiles and first-test setup. |

Tests run with isolated HOME/Git settings. They never launch paid agents.
Mocks replace external boundaries, not the rules being tested.

## Final verification

| Check | Result |
| --- | --- |
| Python suite | 265 passed on laptop and remote development host |
| Desktop logic | 7 Node tests passed |
| Native desktop | All 14 packaged mods passed `herdr-app check` |
| Published source | 246 files checked; 34 generated helpers match their shared sources |
| Installed copies | 402 laptop files and 69 remote files verified |
| Documentation | 11 relative links resolve; setup and workflow examples checked against the commands |
| CI | [Source checks passed](https://github.com/bruno-morel/bollard-herdr/actions/runs/43104621959) |

Code verified at `64ee159`; the closing change only records this audit.
The tests cover failure paths and real disposable Git repositories, not just
happy-path mocks. The terminal smoke test uses real curses screens at 44×24 and
120×50, including resize back to phone width. No paid agent was started.

## Packaging

The distributed Herdr license matches upstream and the installed app. Adapted
components retain their `cloned_from` metadata; origins and modifications are
listed in `THIRD_PARTY_NOTICES.md`. The public preview contains no personal data.

The public repository has the `herdr-layout` topic and the gallery folder contains
its recipe, layout, mods and preview. It meets the [published packaging rules](https://herdr.dev/gallery/#share).
Bollard was **not visible in the gallery when checked**. Discovery is not a
verified release milestone; direct installation from GitHub remains available.

## Keep these constraints

- Herdr loads mods in isolation. Shared sources generate 34 packaged helper
  copies; installer and CI reject stale copies.
- Missing data stays unknown—not clean Git, empty Docker or unused quota.
- Atomic JSON replacement prevents torn files. Callers still own locks.
- Deployments preserve conversations, pins and Claude counters.

## Final checks

```sh
python3 tests/check_sources.py
python3 tests/run.py
node --test tests/js/*.test.mjs
./install.sh all --verify
```

Also check changed desktop mods natively, exercise their controls, and verify
JumpBox. A file split alone does not prove better architecture.
