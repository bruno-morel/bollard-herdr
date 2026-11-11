#!/bin/sh
set -eu
case "${1:-}" in
    desktop|tui|all|laptop|jumpbox) ;;
    *) printf '%s\n' 'Usage: ./install.sh desktop|tui|all [--apply|--verify]' 'Default is a preview. Install dependencies separately; see README.md.'; exit 0 ;;
esac
command -v python3 >/dev/null 2>&1 || { echo 'Python 3 is required.' >&2; exit 1; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$script_dir/install.py" "$@"
