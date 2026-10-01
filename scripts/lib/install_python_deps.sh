#!/usr/bin/env bash
# Library: step 3 of scripts/setup.sh, function-only (sourcing runs nothing).
# Extracted so tests can drive it against a throwaway deps directory.
#
# source: ADR-1063

# install_python_deps_step <scripts_dir> <deps_dir>
# Pre:  caller has defined ok() and fail(), as scripts/setup.sh does.
# Post: deps_dir holds exactly the versions uv.lock pins for the installer
#       set, one *.dist-info per distribution, and one [ok] line is printed;
#       on failure fail() is called and deps_dir keeps its prior entries.
# source: ADR-1092
install_python_deps_step() {
    local scripts_dir="$1"
    local deps_dir="$2"

    echo "Installing Python packages..."
    if ! python3 "$scripts_dir/launcher_deps.py" "$deps_dir"; then
        fail "Dependency install failed (see the error above)"
    fi
    ok "Python packages installed"
}
