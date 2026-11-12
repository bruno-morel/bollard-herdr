#!/bin/sh
set -eu
case "${1:-}" in
    desktop|tui|all|laptop|jumpbox) ;;
    *) printf '%s\n' 'Usage: ./install.sh desktop|tui|all [--apply|--verify|--check-deps]' 'Default is a preview with prerequisite checks and installation guidance.'; exit 0 ;;
esac
command -v python3 >/dev/null 2>&1 || { echo 'Python 3.9+ is required. macOS: brew install python. Linux: install python3 with your package manager. Then rerun this command. See docs/setup.md.' >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo 'Python 3.9+ is required. Upgrade Python (macOS: brew install python), then rerun this command.' >&2; exit 1; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$script_dir/install.py" "$@"
