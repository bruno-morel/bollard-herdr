# Cleanup audit

Status: **in progress**. This is a work list, not a certificate.

| Requirement | Evidence / next check |
| --- | --- |
| No dead workflow paths | Removed unused `work` slot/state functions; audit remaining shell dispatch and Python call sites. |
| Minimal repetition | Found 10 groups of identical desktop helpers; cross-mod imports fail Herdr's boundary check. Design one-source packaging with verified output. |
| Clear architecture | UI/controller/storage boundaries documented; large flow, picker and TUI modules still need responsibility review. |
| Robust tests | Isolated HOME/Git harness; launcher boundaries, installer rollback/cache/preview added. Review, completion, test-runner and UI coverage still need auditing. |
| Short, useful docs | README now links setup/workflow/development guides with diagrams and pasteable examples. Verify remaining recipes/help text against behavior. |
| Preserve live workflows | No sessions restarted; deploy only after relevant checks and inspect both hosts. |

## Verified constraints

- Herdr rejects sibling-module imports outside an individual mod directory.
  Reproduced with a temporary copy of `repo-reader`; live windows were untouched.
- Gallery packages need runnable mod folders. A shared-source build must keep
  the published package usable, not merely make a source-tree linter happy.
- Runtime state and Claude allowance counters must not be reset by cleanup.
