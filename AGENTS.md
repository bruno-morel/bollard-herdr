# Maintaining Bollard for Herdr

Edit the tracked sources, then use install.py for deployment. Never modify
runtime state to make a test pass. Preserve shared stream identity, agent
conversation ownership, checkpoint retry semantics and subscription-only review authentication. Reviews have no fixed call cap;
keep per-call timeouts and the bounded automatic workflow loop. Never enable
paid usage, auto-top-up or provider fallback.
Keep credentials, private pins, machine addresses, terminal IDs and histories
out of Git. Do not launch real agents or review calls as tests.

Run python3 tests/run.py and python3 tests/check_sources.py. Validate changed
Herdr mods with herdr-app check when a desktop runtime is available. Installer
changes must preserve existing personal layouts and reject unrecognized drift.

Shared desktop helpers live in desktop/shared/. Edit those sources and run
python3 desktop_build.py; generated copies in herdr/mods are packaging output.
Run node --test tests/js/*.test.mjs for desktop logic changes (Node 22+).
