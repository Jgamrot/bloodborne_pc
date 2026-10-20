#!/usr/bin/env bash
# Starts the GTK4 launcher from the repository root. The launcher script also falls back to
# launcher/shell.nix when PyGObject, GTK 4 or libadwaita are not installed.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec bash "$root/launcher/bb-launcher.sh" "$@"
