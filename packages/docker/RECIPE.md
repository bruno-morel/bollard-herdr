# Bollard Docker

Compose logs alongside your conversation: bounded history, scroll/follow, copy,
freeze/refresh, startup feedback and a friendly empty state with Start Docker.

Install `mods/bollard-docker/` into the desktop app and `bin/` into `~/.local/bin`
on each repository host (make `bollard-panel.py` executable). Prefer the repository's
`python3 install_mods.py docker --apply`; it checks drift and keeps layouts intact.
Open explicitly with `herdr-app do mod.open '{"name":"bollard-docker"}'`.

Read [installation and Compose scope](../../docs/standalone-mods.md). Regular
projects use standard Compose files; managed Bollard streams retain their isolated
stack through the existing host backend. No agents or reviews are started.
Generated from the same Docker panel used by Bollard's portrait layout.
