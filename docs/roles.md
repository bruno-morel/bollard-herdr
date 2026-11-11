# Customizing roles

In **New conversation**, choose the large Studio / Work role button before
opening a worktree or creating a stream. In the TUI, select the first **Role**
row. Existing conversation selection preserves its role and history. A stream
can host both roles; choosing a role for a new conversation does not convert or
interrupt the existing one.

Customize the two roles in `.bollard/roles.json` at the checkout root. Commit
that file to share it with users and forks. For machine-wide defaults, use
`~/.config/bollard/roles.json` (or `$XDG_CONFIG_HOME/bollard/roles.json`) on the
**agent host**. Repository fields override machine defaults. Omitted fields keep
their defaults. New worktrees inherit committed configuration from their base.

```json
{
  "studio": {
    "label": "Product & marketing",
    "description": "Research, messaging and planning",
    "instructions": "Use evidence-backed recommendations. Record assumptions and open questions in the handoff."
  },
  "work": {
    "label": "Engineering",
    "description": "Implementation, focused tests and review",
    "instructions": "Prefer the project's existing tooling and conventions."
  }
}
```

The desktop and TUI creation pickers read these labels and descriptions from the
selected repository on its host. Startup prompts include the label and extra
instructions. Changes apply to newly launched prompts, not messages already sent
to a running agent. Existing session/status identifiers remain `studio` and `work`.

These are **customizable profiles of two stable lifecycle roles**, not arbitrary
new execution modes. Studio retains planning boundaries; Work retains handoff,
Docker, risk, completion and independent-review behavior. Extra instructions are
additive and must not remove these rules. Claude's review allowance is unchanged.
Adding a third lifecycle role requires implementation and tests across launch,
recovery, ownership, checkpoint and review code; adding a JSON key is rejected.

Labels are at most 40 characters, descriptions 160, instructions 8,000. Invalid
configuration reports its path rather than silently launching with defaults.

## Removed a stream but its name is still taken?

Removing a conversation or checkout can preserve its Git branch. Active
conversations and existing worktrees will not show a branch without a checkout.
Choose **New conversation → Start from → Existing branch**, select the preserved
`codex/<stream>` branch, and choose the desired role/provider. Recovery restores
committed files without resetting the branch. Deleted uncommitted files cannot
be recovered from the branch. Do not delete the branch just to reuse the name.
