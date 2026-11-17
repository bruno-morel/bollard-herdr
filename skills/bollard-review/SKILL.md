---
name: bollard-review
description: Start or inspect an independent Bollard feature review when explicitly requested, preserving subscription-only reviewer settings and current workflow guards.
---

Use installed commands on the agent host from this conversation's verified Git checkout. Derive the stream from `codex/<stream>` and verify the handoff branch identity when present. Stop outside a stream or on a mismatch; never open or recover a different stream.

Run `work review <stream> --status --json`. A status-only request stops here. If a review is active, report its progress instead of launching a duplicate. Review stable implementation and requirements only: if a peer is still modifying the same scope, explain that review must wait for a stable snapshot. Do not stop that peer or claim a stale review approves its new changes.

For an explicitly requested new review:
- Run `work review <stream> --doctor --json` to inspect inputs and account readiness. If inputs are missing, `work review <stream> --prepare` creates/preserves the inputs without calling a reviewer; fill them only from actual acceptance requirements and project test evidence. Report missing requirements or authentication steps clearly. Never read or expose credential files.
- Once ready, use `work review <stream>`. The existing runner starts the independent reviewer separately. Claude is the default; preserve an existing cycle's selected reviewer. The reviewer must differ from the implementation provider. If the current implementation used Claude and no independent reviewer is configured, ask the user to select Codex or Cursor; do not silently substitute a provider. Use `--reviewer` only for the user's explicit selection.
- Use `--follow-up` only when the user requests a recheck after fixes. Do not silently create a new cycle, retry failed model calls indefinitely, increase limits, enable API billing/auto-top-up or bypass readiness/authentication checks. Preserve subscription-only authentication, per-call timeouts and the bounded automatic workflow loop. Do not introduce a new fixed call allowance.

Report queued, checking, reviewing, incomplete and completed states accurately. Read the resulting report when finished; distinguish reviewer findings, missing/stale evidence and completion status. Do not synthesize your own verdict as the independent review, implement fixes automatically, merge, commit or push. Preserve the current agent conversation and never send keys to, stop or restart another agent.
