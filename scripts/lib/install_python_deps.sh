#!/usr/bin/env bash
# Library: step 3 of scripts/setup.sh, function-only (sourcing runs nothing).
# Extracted so tests can drive it against a throwaway deps directory.
#
# source: ADR-1063

# install_python_deps_step <scripts_dir> <requirements_file> <deps_dir>
# Pre:  caller has defined ok() and fail(), as scripts/setup.sh does.
# Post: deps_dir holds exactly the versions requirements_file pins, one
#       *.dist-info per distribution, and one [ok] line is printed; on
#       failure fail() is called and deps_dir keeps its prior entries.
install_python_deps_step() {
    local scripts_dir="$1"
    local requirements="$2"
    local deps_dir="$3"

    echo "Installing Python packages..."
    if ! python3 "$scripts_dir/launcher_deps.py" \
        --requirement "$requirements" "$deps_dir"; then
        fail "Dependency install failed (see pip output above)"
    fi
    ok "Python packages installed"
}
