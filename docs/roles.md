# Custom roles and handoffs

Roles are small prompt profiles, selected in the same **New conversation → Role**
picker in desktop and TUI. Studio and Work remain available without configuration.
An existing conversation keeps its role and history when reopened.

Create `.bollard/roles.json` in your repository and commit it to share your roles:

```json
{
  "research": {
    "base": "studio",
    "label": "Research",
    "description": "Investigate options and document evidence",
    "instructions": "Cite sources and separate findings from assumptions.",
    "handoff_to": ["engineering"]
  },
  "engineering": {
    "base": "work",
    "label": "Engineering",
    "description": "Implement the agreed scope",
    "instructions_file": "roles/engineering.md",
    "handoff_to": ["research"]
  }
}
```

In this example, create `.bollard/roles/engineering.md` with your engineering
instructions. `instructions_file` is optional and relative to the configuration
file's directory. It cannot escape that directory. Inline `instructions` also
work alone. `handoff_to` optionally puts suggested destination roles first; it
does not prevent other destinations.

Machine defaults go in `~/.config/bollard/roles.json` (or
`$XDG_CONFIG_HOME/bollard/roles.json`) **on the agent host**. Repository fields
override machine defaults. New worktrees inherit committed configuration from
their starting branch, so commit repository roles before creating new streams.
You can also customize the labels, descriptions and instructions of `studio`
and `work` directly. Keep IDs stable; removing a selected role produces an
explicit configuration error rather than silently changing the agent's role.

## Hand off to another role

1. Let the current agent finish its task. For an implementation destination,
   build the implementation handoff first with **Studio handoff**.
2. In desktop or TUI, choose **Actions → Hand off to…** and the destination role.
3. Confirm saving the checkpoint. The current agent saves progress and next
   steps, commits intended changes and pushes the stream branch. The controller
   verifies the saved checkpoint before starting the destination role.
4. The same stream stays selected. The destination gets a fresh conversation
   with the shared handoff and its own role instructions.

Progress and errors use the existing checkpoint display and notifications.
A failed save/commit/push keeps the current conversation. Retry preserves verified
steps. An uncertain launch acknowledgement is never automatically replayed:
inspect the destination before trying again, to avoid duplicate conversations.

Shared context lives in `docs/handoffs/<stream>/context.md`; role notes live in
`docs/handoffs/<stream>/roles/<role-id>.md`. Handoff verifies the outgoing role's
saved note too. Agents preserve other roles' notes. Conversation history is not
transferred between providers or roles; the saved documents provide continuity.
You can hand off back and forth without replacing the checkout or resetting Git.

## What stays lightweight and protected

Each profile has one base: `studio` for planning or `work` for implementation.
Profiles add instructions to the existing workflow rather than creating another
execution engine. There remains one lead conversation per base slot per stream.
A handoff refuses to replace an already-open destination slot. Use scoped helpers
for parallel tasks instead of opening competing lead agents.

Work profiles retain Docker setup, risk-based tests, completion checks and the
independent-review rules. Studio profiles retain planning boundaries. A handoff
itself starts no tests, review or helper and does not reset the two-attempt review
allowance. It keeps the selected provider. Role instructions are guidance, not
an operating-system permission boundary.

Existing streams need no migration: missing profile preferences mean Studio or
Work, just as before. Runtime preferences stay outside Git. Configuration changes
apply on the next fresh startup, not to an already-running agent. A handoff
refuses a destination whose configuration changed during checkpointing.

IDs use lowercase letters, numbers and hyphens (start with a letter, max 48).
Labels allow 40 characters, descriptions 160, combined instructions 8,000; each
configuration file allows 32 roles. Invalid configuration reports its path.

## Removed a stream but its name is still taken?

Removing a conversation or checkout can preserve its Git branch. Choose
**New conversation → Existing branch**, select `codex/<stream>`, then the role
and provider. Recovery preserves committed files; it cannot recover deleted,
uncommitted files. Do not delete the branch just to reuse the name.
