#!/bin/sh

set -eu

root=$(git rev-parse --show-toplevel)
hook="$root/.githooks/pre-commit"

if [ ! -f "$hook" ]; then
    echo "Missing versioned hook: $hook" >&2
    exit 1
fi

git -C "$root" config core.hooksPath .githooks
actual=$(git -C "$root" config --get core.hooksPath)

if [ "$actual" != ".githooks" ]; then
    echo "core.hooksPath verification failed: $actual" >&2
    exit 1
fi

echo "Enabled Git hooks for this repository: $actual"
