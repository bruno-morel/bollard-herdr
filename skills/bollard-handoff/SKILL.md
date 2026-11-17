---
name: bollard-handoff
description: Prepare the current Bollard stream's durable implementation handoff when the user requests a handoff. Preserves the current role and conversation.
---

Use the installed Studio/Work commands on the agent host, from this conversation's checkout. Verify the Git root, current branch and `docs/handoffs/<stream>/branch.txt` when present. Derive the stream from the `codex/` branch; stop with a clear explanation outside a stream or on an identity mismatch. Do not create a replacement worktree or guess another stream.

Read the applicable repository instructions and current handoff. Update `context.md` with actual progress, decisions, outstanding work and validation. Keep the brief, decisions, acceptance and references accurate; preserve existing implementation progress and other agents' changes. Do not invent completed tests or overwrite a document another agent is editing.

Run `studio handoff` from the verified checkout. This rebuilds `implementation.md`; it does not switch role, start Work, authorize coding, commit or push. Keep unique notes in the source handoff documents, not only in the generated file. If sources are missing, report what is missing rather than fabricating requirements.

Confirm the generated path and remaining decisions briefly. If asked to display it, use `repo-read --show` with the quoted repository-relative path. Report queued or unsupported phone routing accurately; never replace the agent conversation with a reader.

Do not send keys, stop, restart or take ownership of another agent. Handle this request at a safe task boundary; a busy peer is not permission to interrupt it. Existing workflow checks and normal command approvals still apply.
