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

One initial review plus one follow-up, **shared across reviewers**. Changing the
reviewer never grants more attempts. Only an explicit new cycle does. Failures
after launch consume an attempt; failed preliminary tests do not. No automatic
provider fallback. Missing or malformed evidence stays incomplete.

Claude review uses Sonnet, medium effort, 24 turns and a 20-minute wall limit.
Codex and Cursor use their configured model with the same 20-minute wall limit
and shared attempt counter. Their tools run in read-only/ask modes; the prompt
requires inspection of recorded checks and reporting missing evidence. Claude's
review tools additionally allow up to three declared check reruns. All providers
must produce the same validated verdict. This is not a guarantee of correctness.

Helpers and test setup use the selected provider's account, separately from the
final-review attempt counter. Claude is never selected automatically for those
jobs. First test setup is capped at five minutes; subsequent reruns use no model.
The review launcher rejects API-key environment settings instead of silently
charging a different account. Subscription limits still apply; Bollard's two
attempts are not a token or money quota.

## More providers

The shared adapter is `bin/repo_agents.py`. Adding a name to a picker is not
sufficient: a provider needs installation/authentication support, safe launch and
resume handling, read-only helper mode, structured results, and mocked contract
tests. A quota card alone (for example Gemini) does not imply workflow support.
