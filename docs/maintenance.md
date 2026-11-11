# Cleanup audit

**In progress.** Green tests are evidence, not a graduation ceremony.

| Area | Done | Still to inspect |
| --- | --- | --- |
| Dead code | Removed obsolete shell handlers, duplicate setup and unused imports. | Remaining Python call sites and shell paths. |
| Repetition | Shared desktop helpers, check validation, remote transport, helper presets, CLI help and atomic JSON writes. | Other backend command/state duplication. |
| Architecture | Separate picker, transport, terminal controls, menu and display rows. | Workflow orchestration and remaining panel responsibilities. |
| Tests | Isolated HOME/Git; installer rollback; stream identity; checkpoint retries; completion evidence; bounded review; helper ownership; shell aliases; real-Git merge previews, stale tokens, ignored collisions and conflicts. | Atomic state writes now cover serialization/rename failures, permissions and concurrent writers. Docker log tests cover bounded tails, exits, leases, ownership and retry cooldown. Remaining backend failure paths and interactive UI behavior. |
| Docs | Short setup/workflow guides, diagrams and commands. Checked test commands; shortened the gallery recipe and added first-run guidance. | Remaining command examples and interaction checks. |
| Publication | Check tracked files and unignored candidates across the whole repo. | Final privacy, notices and package audit. |

## Constraints worth keeping

- Herdr rejects imports from sibling mod folders. Shared desktop sources generate
  34 self-contained packaged helpers; installer and CI reject stale copies.
- Missing status data must stay unknown. It is not a clean Git tree, an empty
  Docker stack or zero quota usage.
- Tests never launch paid agents. Review-worker tests replace the model boundary,
  not the evidence checks.
- Deployment preserves conversations, personal pins and Claude counters.

## Before calling this done

```sh
python3 tests/check_sources.py
python3 tests/run.py
node --test tests/js/*.test.mjs
./install.sh all --verify
```

Also check changed desktop mods natively, exercise their controls, and verify
JumpBox. A file split alone does not prove better architecture.
