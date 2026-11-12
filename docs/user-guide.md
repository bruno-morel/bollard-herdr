# Bollard user guide

Keep your conversation open; bring in a tool when you need it. This guide covers
the **studio-work-portrait** desktop layout and the companion terminal interface.
Names below are the default labels; [role profiles](roles.md) can extend or rename Studio
and Work. On narrow windows some controls show only icons—hover for their labels.

## Find what you need

- [Your first stream](#your-first-stream)
- [Arrange the window](#arrange-the-window)
- [Conversation and Questions](#conversation-and-questions)
- [Docker](#docker)
- [Docs, Files and Git](#docs-files-and-git)
- [Tests and Review](#tests-and-review)
- [Actions and helpers](#actions-and-helpers)
- [Information rail](#information-rail)
- [Terminal and phone](#terminal-and-phone)
- [Recovery and common surprises](#recovery-and-common-surprises)

## Your first stream

A **stream** is a branch and checkout for a piece of work. A **conversation** is
an agent's chat inside that stream. A **view** is where the app displays it.
Removing a view, starting a fresh chat and deleting a worktree are different actions.

1. Click **Choose a stream**, or the repository/stream name above a conversation.
2. Choose **Existing conversation** to return to a live terminal without starting
   another agent. Choose **New conversation** to open or prepare a checkout.
3. For a new conversation, choose **Studio** (planning and documents) or **Work**
   (implementation, tests and Docker), then the machine and repository.
4. Choose the starting point below, select Codex, Claude or Cursor, and submit.
   Watch the opening progress; use Retry after a reported failure rather than
   repeatedly submitting the same request.

| Start from | Use it when… | What is preserved |
| --- | --- | --- |
| New stream | You want independent work from the default branch or another selected base. | The base branch; a separate stream checkout is prepared. |
| Existing worktree | The branch already has a checkout on this machine. | Its files, branch and stream identity. |
| Existing branch | A local or fetched remote branch exists without an open checkout. | Existing local commits; recovery does not overwrite them with a remote version. |

Branch choices reflect available local/fetched references. Fetch when you need
new remote branches. A checkout folder and stream name are normally filled together;
use customization only when you need a different folder. Existing checkouts keep
their identity. Install and sign in to the selected CLI **on the agent machine**.

Studio and Work can use the same stream and handoff, but have separate
conversations. Switching the role for a new conversation does not rewrite the
role of a live chat. Coordinate overlapping edits between agents.

## Arrange the window

The default has two stacked stream views. Each has its own toolbar, large
conversation, optional tool panel **above** it and optional information rail on
the right. Changing one view's tool does not change the other stream.

| Window control | What it does |
| --- | --- |
| Spaces & agents | Show/hide the sidebar for browsing spaces and agent activity. |
| Add stream → Below | Add a stream view in a vertical stack. |
| Add stream → Beside | Add a view alongside the others. |
| Split a stream → top/bottom or left/right | Choose which view to split, then choose the conversation for the new slot. |
| In a separate Herdr window | Pick a stream for a separate desktop window, useful on another display. |
| Remove stream view | Choose a layout slot to remove. This removes the view, not the Git branch or agent. |
| Repository / stream name | Reopen the picker to change what this slot displays. |
| Information icon | Show/hide this stream's information rail. |

The toolbar groups related tools: **Conversation / Questions**, **Docs / Files /
Git**, and **Tests / Review**. A group's title follows the selected tool. **Actions**
is a menu of operations, rather than a viewer. **Conversation** returns attention
to the chat and closes the optional tool view.

Yellow can indicate attention needed or completed agent work; red indicates a
reported failure. Read the panel details: a color alone is not a test verdict.

## Conversation and Questions

| Control | Use |
| --- | --- |
| Conversation | Focus the existing agent terminal. Chat and approvals remain with that agent. |
| Questions | Show agents or workflows that need input. |
| Open question | Open the relevant terminal so you can answer its actual prompt. |

Questions depend on reported agent/workflow state. An empty panel does not prove
that every CLI has no pending approval. Check the conversation if an agent appears
stuck. Never approve a command solely to clear a badge.

After an agent exits, its terminal stays available. The launcher menu is explicit:

| Input | Result |
| --- | --- |
| `n` / `new` | Start a new chat with the current role/handoff prompt, in the same checkout. |
| `r` / `resume` | Open the selected agent's saved-history picker. |
| `r <ID>` | Resume a specific saved conversation. |
| `codex`, `claude`, `cursor` | Select the provider only; then choose New or Resume. |
| `n cursor` (or another provider) | Select that provider and start a new chat. |
| `s` / `shell` | Open a shell in this checkout. Exit the shell to return to the menu. |
| Enter | Redisplay the menu without launching anything. |

For an intentional fresh start after real work, prefer the checkpoint action below
so the outgoing agent saves context first. Chat history is not shared between CLIs.

## Docker

Docker shows the selected stream's Compose logs. Opening it does not start a stack.
Container health and memory summaries live in the Information rail.

| Control | Effect |
| --- | --- |
| Start Docker | Prepare/start this stream's stack. It can build images and create containers; watch startup progress. |
| Startup output / Back to containers | Inspect startup output or return to container logs. |
| Retry startup | Retry a failed stack start after fixing its cause. |
| View last logs / Back to overview | Read retained logs when the stack is not active. |
| Following / Latest | Follow new output or jump back to the newest logs after scrolling away. |
| Freeze / Resume refresh | Pause/resume the viewer's updates; it does not pause containers. |
| Copy logs | Copy the currently displayed log text. |
| Refresh icon | Refresh the stream's Docker information. |
| Show details / Try again | Inspect an actual connection/configuration failure and retry reading it. |
| Ask a helper | Send the displayed log context to a separate read-only helper. |

The whale empty state means there is no active prepared stack to display. An actual
Docker access error has details; it is not treated as an empty healthy stack.

## Docs, Files and Git

Use the grouped picker to change the kind of content without replacing the chat.

| View | Contents |
| --- | --- |
| Docs | Markdown and `.txt` files. Markdown is rendered for reading. |
| Files | Repository files and their full current contents. |
| Git | Changed files and diffs, with the file hierarchy beside the change preview. |

Docs and Files prefer modified files when there are any; otherwise they show all
eligible files. **All files** lets you widen the list. Search filters paths.
The **Folders**, **File types** and **List** icons change grouping; expand directory
rows or use **Collapse folders** to reduce scrolling. Git provides the same grouping
choices for its changed-file list.

### Reading and editing

| Control | Effect |
| --- | --- |
| File row | Open that file in the tool panel. |
| File list / Hide list | Show/hide navigation to give the content more room. |
| Source / Preview | Switch Markdown between raw text and rendering. |
| Edit / Restore edit | Enter the editor or return to an existing draft. |
| Save | Write the edit to the selected checkout. It does not commit or push. |
| Keep draft / preview | Leave editing for preview while retaining the draft; this is not a saved file. |
| Refresh icon | Reload the file list and current file. |
| Ask a helper | Use the displayed document as context for a separate helper. |

You can also ask the lead, “Show me docs/…”. Its prompt tells it to route the file
to this viewer using `repo-read --show`, keeping the agent conversation separate.
If the target stream is not selected, the request may remain queued until you
select it. A queued request is not yet an opened file.

### Git operations

| Control | Effect |
| --- | --- |
| Stage / Unstage | Change the selected file's staging state. Unstage keeps its working edits. |
| Commit message + Commit staged | Commit already-staged changes; it does not automatically stage everything or push. |
| Update from main | Open a preview of merging the repository's default branch into this stream. |
| Merge branch… | Choose another branch/worktree's committed tip as the source. |
| Preview | Inspect incoming commits, changes and blockers before applying. |
| Fetch & preview | Update remote references, then inspect the proposed merge. |
| Merge into … | Apply the previewed merge when allowed. |

A source worktree contributes **committed changes only**. This is a merge into the
current stream—not a branch switch, rebase, automatic stash or push. Active work,
dirty/conflicting state or a stale preview can block it. Resolve the cause and
preview again; do not force a merge just to clear the panel.

## Tests and Review

These share one picker but do different jobs. **Tests** runs configured project
commands. **Review** asks an independent agent to assess evidence and implementation.
Opening either panel alone does not start a model review.

### Tests

| Control | Effect |
| --- | --- |
| Provider choice before first setup | Choose the child agent that inspects the project's existing test tooling. |
| First tests run | Start that separate setup helper, validate/save finite checks, then run them. The lead chat stays available. |
| Open test helper | Inspect the setup child if it needs attention. |
| Rerun tests | Run the saved project commands; no model is needed for a normal rerun. |
| Show / Hide commands | Inspect exactly what is configured to run. |
| Logs / Hide logs on a result row | Read output for that check. |
| Copy output | Copy the opened check's output. |
| Find why and fix | Replaces Rerun tests when failures are captured. Use the idle lead immediately, or automatically start read-only diagnosis and queue repair until the busy lead is idle. |
| Refresh icon | Read current run state without starting another run. |

Result rows represent configured checks/commands. Detailed test counts depend on
available project reports; unknown counts stay unknown. Timeouts, interrupted runs,
skipped coverage and incomplete results are not silently counted as passed.

Checks live in the stream's `tests-input.json`, with a review-input fallback.
See [focused validation and completion](workflow.md#check-completion-without-rerunning-tests)
for low/medium/high-risk expectations. A small visual edit should have focused
component/browser evidence, not an automatic full regression run.

### Review and completion

| Control | Effect |
| --- | --- |
| Reviewer choice | Choose Claude (default), Codex or Cursor. It must differ from the implementation provider. |
| Prepare inputs | Create the acceptance/evidence inputs to fill before review. |
| Open inputs | Inspect existing review inputs. |
| Start review | Run the initial independent review when prerequisites are satisfied. |
| Review fixes | Use the cycle's one follow-up after addressing findings. |
| New review cycle | Explicitly authorize a further cycle; the confirmation explains the extra allowance. |
| Check completion | Check the risk assessment and current evidence; do not rerun tests or call a reviewer. |
| Refresh icon | Read the latest review/completion status. |
| Ask a helper | Discuss the report separately; this does not turn an unverified review into approval. |

The panel shows risk, passed evidence and missing/stale requirements. **Completed**,
**Completed with limitations** and **Blocked** have different meanings; read the
limitations rather than treating every receipt as independent approval. A changed
source version can invalidate a previous review.

If the reviewer is unavailable, use **Install guide**, **Sign in**, **Open sign-in**,
**Copy command** and **Check again** as offered. Authentication happens on the agent
host. Review is not allowed to silently switch providers or hide missing evidence.

One initial review and one follow-up share the same two-attempt budget across
providers. Changing reviewer does not refill it. Consult the [current review limits](agents.md#review-limits-and-usage)
for model settings and timeout details. A successful check or review never grants
permission to merge or publish automatically.

## Actions and helpers

| Action | What happens |
| --- | --- |
| Hand off to… | Pick a custom or built-in role, save and verify the checkpoint, then start that role on the same stream. [Configuration and safeguards](roles.md). |
| New conversation · same stream | Ask the current agent to save context, commit and push the checkpoint, then restart the conversation. This **does write commits and push**. |
| Open Studio conversation | Open/reuse the planning role for this stream. |
| Open Work conversation | Open/reuse the implementation role, including its Work setup. |
| Prepare implementation | Build/update the handoff, then ask Work to write an implementation plan and report readiness before coding. |
| Implement → Review | Start the guided implementation/validation/review flow with the selected implementer and independent reviewer. |
| Add scoped helper | Give a separate agent a bounded task; choose read-only research or isolated coding. |
| Pause workflow | Request a pause of the managed workflow. A current bounded operation may finish first; this is not a container stop or branch deletion. |

Checkpoint and opening progress show their current step. On failure, read the
message, fix the cause and use **Retry unfinished step** / **Retry**. Retrying
revalidates state; it does not blindly repeat a successful commit or open more windows.

### Ask a helper about this

Pane helper buttons carry a snapshot of the selected document, diff, log or report.
Review the context and question before submitting. The helper opens separately;
the lead conversation stays in place.

| Preset | Scope |
| --- | --- |
| Investigate failure | Explain evidence, separate hypotheses and propose the smallest next check/fix. No edits or test execution. |
| Pre-publication check | Check claims, links, tracking, consistency and missing assets. No publishing or edits. |
| Campaign follow-up | Read connected analytics for the requested dates/comparison and suggest a measurable experiment. No scheduling, posting, spending or recurring monitor. |

Codex and Cursor are the default helper choices; Claude can be selected explicitly.
Missing analytics access must be reported, not invented. These read-only helpers
are different from **isolated coding helpers** in Actions: coding helpers get their
own worktree, and their changes still need integration by the lead.

## Information rail

Open **Information**, then use its icon row to switch cards. The close icon hides
only the rail; Refresh reads current data.

| Card | What it tells you |
| --- | --- |
| Agents & progress | Stream agents, activity and available model/reasoning details. Unreported details remain unknown. |
| Conversation context | Available context-use information for the conversation. Not every provider reports the same data. |
| Usage & limits | Reported allowance windows, usage meters, reset information and account setup links. |
| Docker containers | Container state/health, uptime and memory usage/limit when reported. |
| Git status | A compact view of this stream's repository state. Use Git above for diffs and operations. |

Usage readings are snapshots, not billing guarantees. Codex may report short and
weekly windows; Claude usage can be read without sending a chat. The local review
attempt budget is separate from either subscription's quota. Cursor's exact quota
is not exposed here—**Usage ↗** opens its dashboard. A Gemini setup/limits card does
not mean Gemini is supported by the workflow launcher. Available providers and
setup instructions are listed in the [agent guide](agents.md).

## Terminal and phone

Run `repo-tui` for Bollard's terminal interface. On installations with the optional
Herdr launcher wrapper, plain `herdr` opens it. Desktop and terminal attach to the
same remote terminals; they do not copy conversations onto the phone or laptop.

The terminal interface offers the stream picker, chat, Docs/Files/Git, Docker,
Tests/Review, information and workflow actions. It adapts to narrow displays;
follow its visible key hints rather than expecting desktop pixel-for-pixel parity.
Desktop-only window arrangement controls do not create phone windows.

| Interaction | TUI behavior |
| --- | --- |
| Herdr prefix + `o` | Change stream through the shared picker. |
| Prefix + `t` | Open tools. |
| Prefix + `i` | Open information. |
| Prefix + arrow keys | Move focus between panes. The prefix is your Herdr-configured prefix. |
| Docs/Files: `/`, `a`, Enter, Tab | Filter, toggle all/modified, open a file, move to preview. |
| Rendered Markdown: Links / Back | Follow a document link in the Docs pane and return to your previous place. |
| Panel footer hints | Refresh, helper, copy and back controls where available. |

Agent-requested file opening works here too: ask to see the file, and Docs opens
it separately from the conversation. On a phone, rendered Markdown and the link
picker avoid needing tiny mouse targets. Agent input keys still belong to the CLI
when its terminal has focus.

## Recovery and common surprises

| Symptom | Next step |
| --- | --- |
| No sessions found | Resume has no saved chat for that provider/workspace. Exit its picker and choose `n` if this is the first conversation. |
| Cursor keychain/login error | [Unlock and authenticate on the agent Mac](agents.md#cursor-recovery-on-a-remote-mac). Recreating a stream cannot fix authentication. |
| Stream exists but no worktree is listed | Its Git branch may have survived removal. Choose Existing branch to restore the checkout. |
| Stream says not open | The checkout exists, but a recognized lead conversation is not available; inspect/open its terminal. It is not proof the files are gone. |
| Review button unavailable | Inspect account readiness, inputs and remaining attempts. Opening the panel does not start a review. |
| Test result is stale | Source or configured checks changed; obtain evidence for the current version. |
| Operation timed out | Inspect the existing operation/terminal before retrying; it may have succeeded. |

For transfer, safe removal and finishing merged work, see [Daily workflow](workflow.md).
For installation, SSH and platform limits, see [Setup](setup.md).

### Closing a stream view after removing its worktree

Use the minus button at the top of the layout, then choose the stream view.
Closing a view does not require its worktree or terminal to still exist. The
last view offers to quit this Herdr instance or keep an empty reusable slot.
Closing the window leaves its agents and other Herdr windows running. Unsaved editor text prompts you to
save it or explicitly discard it before closing.

This clears the view's selection and pending display requests. Running agents,
Docker resources, Git branches and files are preserved; deleting a worktree or
stopping an agent is a separate action. To change from planning to coding on
an existing stream, use **Hand off to… → Work** rather than deleting it.
New conversations show prominent **Studio · Plan** and **Work · Implement**
choices; configured custom roles appear in the same switch, without a second
role dropdown.

### Published Docker ports and test freshness

The optional right-hand information panel’s **Docker containers** view shows
compact published-port badges aligned right with their copy controls inside each
container card. Container port/protocol and RAM-limit details are available on hover. The main Docker pane stays focused on logs. Use the copy icon to copy the host address, or the browser icon to open a web URL
when the protocol is declared or suggested by a common web port. Suggested URLs are
labelled; the panel does not probe the service. Remote addresses use the Docker
host, not the laptop. Remote loopback bindings need an SSH tunnel and do not
get a misleading clickable web URL. Database and UDP ports remain plain addresses.

**Stale** test rows describe historical commands, not current code. Their original
outcomes and logs remain available. Tests invoked directly in an agent conversation
are not automatically imported into the Tests pane. The standalone runner only
runs saved checks; it never fixes application code automatically. **Find why and
fix** is the explicit repair action (also a tappable button / **R** in the TUI).
It verifies stale failures first, handles broken runner commands as well as product
bugs, and preserves existing changes. When the lead is busy, one bounded read-only
Codex/Cursor helper investigates (up to five minutes); the controller waits up to
24 hours for that same lead to become idle, then sends the diagnosis and repair
request automatically. It never writes into the busy checkout or interrupts the
lead. If newer test evidence replaces the failures, the queued request is retired.
Progress appears in Tests on desktop and TUI. Repeated clicks reuse the request;
uncertain delivery is never retried automatically. Missing/closed agents and
helper failures are reported explicitly. This does not start a Claude review,
reset allowances, merge or push. A sent request is not a verified test pass. If delivery is uncertain, inspect the
conversation before retrying. **Implement → Review** remains the separate bounded
implementation and independent-review flow.

CLI equivalent: `work tests fix <stream> --target tID --json`. A normal model-free
rerun remains available with `work tests run <stream>`.

### Repair handoff recovery

A completed (`done`) lead can receive a repair just like an idle lead. Busy leads
keep their current task; the repair coordinator waits. A structured Herdr refusal
that explicitly says nothing was typed is safe to retry. Lost acknowledgements
remain blocked to prevent duplicate instructions. Retrying a legacy rejected
handoff reuses its saved diagnosis when the test run and lead still match; it
does not spend another model call. Old failing results are evidence to verify,
not proof that the current code still fails. No Claude review is started by this
recovery.

### Test repair progress

Tests shows a compact coloured stage and check totals in desktop and TUI:
**Investigating → Fixing → Rerunning tests**, followed by fresh passed/failed
results. **Waiting for lead** means the current task continues uninterrupted.
**Repair requested** confirms delivery only. Existing conversations that have
not reported a stage show **Agent working · stage not reported**; when finished,
**Awaiting verification** offers **Verify fix**. Old results are labelled
**Previous run**, never presented as proof of a successful repair.

New repair prompts report stages with `work tests progress <stream> --run <run-id>
--phase investigating|fixing|awaiting-tests|blocked --message 'short detail'`
(select one phase). These reports cannot grant passing status. Only the saved
runner results establish check outcomes; direct shell tests are not silently
imported. Logs remain available per check. Hover the stage for extra detail.
No extra reviewer calls or Claude allowance changes are involved.
