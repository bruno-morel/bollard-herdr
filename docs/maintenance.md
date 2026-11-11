# Cleanup audit

Status: **in progress**. This is a work list, not a certificate.

| Requirement | Evidence / next check |
| --- | --- |
| No dead workflow paths | Removed unused `work` slot/state functions; audit remaining shell dispatch and Python call sites. |
| Minimal repetition | Shared desktop sources now generate 34 self-contained helpers; installer/CI reject drift. Continue auditing backend duplication. |
| Clear architecture | UI/controller/storage boundaries documented; large flow, picker and TUI modules still need responsibility review. |
| Robust tests | Isolated HOME/Git harness; launcher boundaries, installer rollback/cache/preview added. Added real-Git file browsing, routing isolation and stream split/removal tests. Added completion evidence/receipt tests and review allowance boundaries. Full review worker, test-runner and remaining backend paths still need auditing. |
| Short, useful docs | README now links setup/workflow/development guides with diagrams and pasteable examples. Verify remaining recipes/help text against behavior. |
| Preserve live workflows | No sessions restarted; deploy only after relevant checks and inspect both hosts. |

## Verified constraints

- Herdr rejects sibling-module imports outside an individual mod directory.
  Reproduced with a temporary copy of `repo-reader`; live windows were untouched.
- Gallery packages need runnable mod folders. A shared-source build must keep
  the published package usable, not merely make a source-tree linter happy.
- Runtime state and Claude allowance counters must not be reset by cleanup.
