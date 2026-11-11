# Cleanup audit

**In progress.** Green tests are evidence, not a graduation ceremony.

## Verified so far

| Area | Evidence |
| --- | --- |
| Dead paths | Removed obsolete shell handlers, duplicate setup and unused imports. |
| Shared logic | Desktop helpers, check validation, transport, presets, CLI help, atomic JSON writes, Compose validation. |
| Boundaries | Picker, transport, terminal input, menu, display rows and refresh queries live outside workflow controllers. |
| Workflow tests | Stream identity, checkpoint retries, completion evidence, bounded review, helper ownership and ambiguous task delivery. |
| Git tests | Real disposable repos: merge previews, stale tokens, ignored files and conflicts. |
| Failure tests | Installer rollback, interrupted writes, Docker ownership, stream-switch races, transfer/recovery failures, quota refresh and worktree removal. |
| Docs | Short guides, diagrams, checked relative links, installer profiles and first-test setup. |

Tests run with isolated HOME/Git settings. They never launch paid agents.
Mocks replace external boundaries, not the rules being tested.

## Remaining audit

- **TUI:** document routing, render-before-ack and history have automated checks.
  Exercise the actual picker and panels, including phone-sized resizing.
- **Cleanup:** verify `work finish` recovery after a remote deletion failure.
  Its current order removes the local checkout before pushing the deletion.
- **Packaging:** finish the upstream notice comparison and gallery discovery check.
- **Final pass:** run the full checks against the final commit and verify both hosts.

These are review tasks, not instructions to split every large file.

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
