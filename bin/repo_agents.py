"""Supported agent capabilities and bounded, read-only child invocations."""

import json
import shutil

AGENTS = ("codex", "claude", "cursor")


def executable(name):
    if name not in AGENTS:
        raise RuntimeError("Unknown agent: " + str(name))
    for candidate in (("cursor-agent", "agent") if name == "cursor" else (name,)):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError(
        name + " CLI is missing; see docs/agents.md and sign in on this host"
    )


def claude_read_only():
    # Remove editing, shell, delegation, hooks and unrelated MCP integrations.
    return [
        "--tools",
        "Read,Glob,Grep",
        "--allowedTools",
        "Read,Glob,Grep",
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "",
        "--settings",
        '{"disableAllHooks":true}',
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    ]


def structured_argv(name, binary, root, folder, prompt):
    if name == "codex":
        return [
            binary,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--cd",
            str(root),
            "--output-schema",
            str(folder / "schema.json"),
            "--output-last-message",
            str(folder / "result.json"),
            prompt,
        ]
    if name == "claude":
        return [
            binary,
            "-p",
            "--model",
            "sonnet",
            "--effort",
            "medium",
            "--max-turns",
            "24",
            "--output-format",
            "json",
            "--json-schema",
            (folder / "schema.json").read_text(),
            "--no-session-persistence",
            *claude_read_only(),
            prompt,
        ]
    if name == "cursor":
        return [
            binary,
            "--print",
            "--mode",
            "ask",
            "--sandbox",
            "enabled",
            "--workspace",
            str(root),
            "--output-format",
            "json",
            prompt,
        ]
    raise RuntimeError("Unsupported structured agent: " + str(name))


def structured_result(name, folder, log="agent.log"):
    path = folder / ("result.json" if name == "codex" else log)
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise RuntimeError("Agent returned no bounded result; inspect its log")
    value = json.loads(path.read_text())
    if name != "codex":
        if (
            not isinstance(value, dict)
            or value.get("is_error")
            or value.get("subtype") not in (None, "success")
        ):
            raise RuntimeError(name + " did not finish successfully")
        value = (
            value.get("structured_output") if name == "claude" else value.get("result")
        )
        if isinstance(value, str):
            value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("Agent did not return a JSON object")
    return value
