# Resolve the caller's checkout, including linked worktrees and subdirectories.
[[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" == true ]] ||
    die "run this command inside a Git-controlled source tree"
ROOT="$(git rev-parse --show-toplevel)"
COMMON="$(git rev-parse --git-common-dir)"
COMMON="$(cd "$COMMON" && pwd -P)"
REPO_ID="$(printf '%s' "$COMMON" | shasum -a 256 | cut -c1-16)"
CHECKOUT_ID="$(printf '%s' "$ROOT" | shasum -a 256 | cut -c1-16)"
PROJECT="${ROOT:t}"
RUNTIME="${XDG_STATE_HOME:-$HOME/.local/state}/repo-tools"
# Runtime files must never be placed in this repository by an XDG override.
umask 077
mkdir -p "$RUNTIME"
RUNTIME="$(cd "$RUNTIME" && pwd -P)"
[[ "$RUNTIME" != "$ROOT" && "$RUNTIME" != "$ROOT/"* ]] || die "state directory must be outside the repository"
ensure_scratch() {
    local checkout="$1"
    [[ ! -L "$checkout/scratch" && ! -L "$checkout/.gitignore" ]] || die "scratch/.gitignore must not be symlinks"
    [[ -z "$(git -C "$checkout" ls-files -- scratch)" ]] || die "scratch contains tracked files; relocate or untrack them first"
    if ! git -C "$checkout" check-ignore -q --no-index scratch/.repo-tools-probe; then
        printf '\n# Temporary and large generated assets\n/scratch/\n' >> "$checkout/.gitignore"
    fi
    mkdir -p "$checkout/scratch"
}

# Only Zellij-facing commands need its socket alias. Herdr preparation and
# document operations must work without inspecting another interface's state.
case "${1:-}" in
    prepare|path|init|idea|asset|handoff|prompt|copy|list|ls|agent-prompt|_herdr-start|_herdr-pane|_herdr-env) return 0 ;;
esac
# Short Zellij socket path v1
if [[ "$OSTYPE" == darwin* ]]; then
    ZELLIJ_SOCKET_DIR="$(python3 "${${(%):-%N}:A:h}/repo-zellij-socket.py")" || return 1
    export ZELLIJ_SOCKET_DIR
fi
