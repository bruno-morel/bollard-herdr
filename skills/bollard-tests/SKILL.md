---
name: bollard-tests
description: Run or inspect the current Bollard stream's project checks when the user requests tests, using the existing finite runner and risk-based test scope.
---

Use installed commands on the agent host. Verify this conversation's Git checkout, `codex/<stream>` branch and handoff branch identity; stop outside a stream or on a mismatch. Preserve the current role, checkout and conversation.

1. Run `work tests status <stream> --json`. If a run is queued, preparing or running, report it instead of starting another. A status-only request stops here.
2. For a requested run with configured checks, use `work tests run <stream>`. This queues the existing finite runner. It does not call Claude or automatically repair code.
3. If checks are not defined, use `work tests first <stream> --target "$HC_TERMINAL_ID" --agent codex` (or `--agent cursor` for a Cursor conversation). First verify that the terminal ID is present and identifies this stream's lead, not a helper: inspect `hc get "$HC_TERMINAL_ID" --json`. Never guess a terminal ID. Without a verified lead, explain how to open the stream's Tests pane to select one. The first-run child selects existing project tooling and launches the first run; do not add another test framework or call Claude for setup.

Follow repository risk assessment and focused-test rules. Small visual changes need affected component/browser checks; behavioral changes need relevant integration/regression coverage. Do not broaden the suite merely to fill time, weaken assertions, or mark skipped/interrupted/timed-out checks as passed.

Read status again to distinguish queued work from completed evidence. Report what passed, failed or remains unverified; offer the existing Find why and fix action for failures rather than silently starting repairs or reviews. Do not poll in a tight loop. Use `work complete <stream> --status --json` only if completion status is requested; never equate passing tests with independent review approval.

Do not interrupt other agents, send them keys or restart sessions. Coordinate overlapping edits and tests against a changing checkout; report stale evidence honestly. Normal approvals and existing runner guards remain authoritative.
