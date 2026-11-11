# Source from ~/.zshrc to open the Studio/Work dashboard by default.
function herdr {
    if (( $# == 0 )); then
        command "$HOME/.local/bin/repo-tui"
    else
        command herdr "$@"
    fi
}
