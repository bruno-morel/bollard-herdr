# Agents: install, sign in, choose

Install the CLIs on the machine **running the conversations**. For a laptop
connected to a server, that usually means the server. Installing Cursor's editor
on the laptop does not install its agent CLI on the server. Accounts and CLI
histories stay on that host; Bollard never copies credentials between machines.

## Install and authenticate

### Codex

With Node.js/npm installed:

```sh
npm install -g @openai/codex@latest
codex login
codex login status
```

Use your ChatGPT account for subscription usage. See the official
[installation commands](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)
and [authentication guide](https://learn.chatgpt.com/docs/auth?surface=cli).
Run the same npm installation command to update.

### Claude Code

On macOS with Homebrew:

```sh
brew install --cask claude-code
claude auth login
claude auth status
```

Choose your Claude subscription login, not Console/API billing for bounded
reviews. Update a Homebrew installation with `brew upgrade --cask claude-code`.
Other platforms: [official setup](https://code.claude.com/docs/en/setup).
Authentication commands: [CLI reference](https://code.claude.com/docs/en/cli-reference).

### Cursor Agent

```sh
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"
agent login
agent status
```

Bollard also accepts the older `cursor-agent` executable, preferring it when both
names exist. If that is your installed name, use `cursor-agent login` and
`cursor-agent status`. See [installation](https://cursor.com/docs/cli/installation)
and [authentication](https://cursor.com/docs/cli/reference/authentication).

For remote sign-in, start the command on the server and open its complete login
URL in your laptop browser. Copy it without spaces or line breaks. Cursor can
print its URL using `NO_OPEN_BROWSER=1 agent login`. If a sign-in window fails,
run the provider's status command on the server; a successful desktop login is
not evidence that the remote CLI is connected.

## Choose an agent for each job

| Job | Supported choices | Default / behavior |
| --- | --- | --- |
| Studio planning | Codex, Claude, Cursor | Codex; role rules and shared handoff |
| Work implementation | Codex, Claude, Cursor | Codex; existing Work/Docker setup |
| Read-only pane helper | Codex, Claude, Cursor | Codex, or Cursor from a Cursor pane; Claude is explicit |
| Isolated coding helper | Codex, Claude, Cursor | Codex; separate worktree; lead integrates |
| First test setup | Codex, Claude, Cursor | Codex; CLI may inherit Cursor from its lead |
| Test reruns / completion check | No model | Existing project commands / evidence |
| Independent final review | Claude, Codex, Cursor | Claude; must differ from implementation provider |

Desktop and TUI offer these choices in their stream, helper, test and review
controls. Picking a provider does not convert a running conversation's history.
An existing role keeps its owner; exit/switch through its agent chooser or use
the checkpoint/new-conversation flow. Read the shared handoff when changing
providers. The planning/implementation prompts, repository instructions, risk
policy and completion checks apply to all three.

From inside your repository:

```sh
studio herdr my-feature --agent cursor
work herdr my-feature --agent codex
work flow helper my-feature --role work --agent claude --scope 'Inspect the failure report; do not edit'
# Replace tID with the lead terminal from hc ls:
work tests first my-feature --target tID --agent cursor
work tests run my-feature
work review my-feature --reviewer claude --doctor
work review my-feature --reviewer claude
work complete my-feature --status
```

For implementation through review with a different pairing:

```sh
work flow implement my-feature --agent claude --reviewer codex --task 'Implement the agreed handoff'
```

The Work agent must match the existing conversation, if one is running. Review
reads the saved Work provider. For a stream implemented outside the launcher,
pass `--implemented-by codex|claude|cursor`; it cannot contradict a saved provider.
The check distinguishes CLIs, not underlying model vendors: Cursor can use models
from several vendors, so choose a genuinely different model when that matters.

## Review limits and usage

Reviews have **no fixed call-count cap**. You can request further reviews without
resetting an allowance; historical calls and reports remain recorded. Failed
preliminary tests do not call a model. One Implement → Review run performs at
most four review rounds, stopping on incomplete evidence or provider limits.
There is no automatic provider fallback or repeated retry after a quota error.

Claude review uses Sonnet, medium effort, 24 turns and a 20-minute wall limit.
Codex and Cursor use their configured model with the same 20-minute wall limit
and recorded call history. Their tools run in read-only/ask modes; the prompt
requires inspection of recorded checks and reporting missing evidence. Claude's
review tools additionally allow up to three declared check reruns. All providers
must produce the same validated verdict. This is not a guarantee of correctness.

Helpers and test setup use the selected provider's account, separately from the
final-review attempt counter. Claude is never selected automatically for those
jobs. First test setup is capped at five minutes; subsequent reruns use no model.
The review launcher rejects API-key environment settings instead of silently
charging a different account. Subscription limits still apply. Bollard never
purchases credits, enables extra usage or auto-reload, or raises spending limits.
**Disable Usage credits / extra usage in Claude Settings → Usage** for a strict
subscription-only stop. Auto-reload off alone still permits spending an existing
paid balance. Bollard cannot verify or change this account setting from the CLI.
See [Claude’s usage-credit settings](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans).

## More providers

The shared adapter is `bin/repo_agents.py`. Adding a name to a picker is not
sufficient: a provider needs installation/authentication support, safe launch and
resume handling, read-only helper mode, structured results, and mocked contract
tests. A quota card alone (for example Gemini) does not imply workflow support.

## Cursor recovery on a remote Mac

Install and authenticate Cursor on the machine running the agent. Installing it
on the laptop alone does not install it on an SSH host. If login reports
`errSecInteractionNotAllowed` / `security exit code 36`, unlock the login keychain
in a shell **on that host**, then authenticate:

```sh
security unlock-keychain
cursor-agent login
cursor-agent status
```

Enter the host account's password at the secure prompt; never put it in a command,
configuration file, handoff or chat. Installations named `agent` can use `agent`
in place of `cursor-agent`. Do not disable keychain protection to work around this.

A failed first login may leave a valid stream with no saved conversation. If the
resume picker says **No sessions found**, exit it, then choose **n (new chat)** at
the existing terminal's launcher menu. This starts the first conversation in the
same checkout and role; it does not create another stream. If history does exist,
select it instead. Reopening a terminal is not proof authentication succeeded.

## Conversation launcher menu

After an agent exits, choose **n / new** to start a new conversation with the
role and handoff prompt, or **r / resume** to select saved history. `r <ID>`
resumes a specific conversation. Typing `codex`, `claude` or `cursor` only
selects the provider; it does not start anything until you choose New or Resume.
`n cursor` selects Cursor and starts fresh in one step. Enter redisplays the menu.
A new conversation keeps the current checkout and files. Use the checkpoint
workflow first if the outgoing conversation has progress to save.
