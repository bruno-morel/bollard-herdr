# Bollard Files

A repository browser alongside your agent conversation: Docs, Files and Git in
one panel, with directory/type/list views, changed-first selection, native
Markdown/source rendering, safe text editing and Git diffs/staging/commits.

Install `mods/bollard-files/` into the desktop app and `bin/` into `~/.local/bin`
on each repository host (make `bollard-panel.py` executable). Prefer the repository's
`python3 install_mods.py files --apply`; it checks drift and keeps layouts intact.
Open explicitly with `herdr-app do mod.open '{"name":"bollard-files"}'`.

Read [installation and behavior](../../docs/standalone-mods.md). This package is
generated from Bollard's existing panels; do not edit generated copies. No roles,
agents, reviews, worktrees or layout replacement are required.
