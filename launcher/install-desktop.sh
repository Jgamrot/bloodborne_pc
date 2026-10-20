#!/usr/bin/env bash
# Adds the launcher to the application menu (~/.local/share/applications) for this checkout.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
data=${XDG_DATA_HOME:-$HOME/.local/share}
dest=$data/applications
icons=$data/icons/hicolor/256x256/apps
mkdir -p "$dest" "$icons"
install -m 644 "$here/bloodborne.png" "$icons/io.github.bbport.Launcher.png"
python3 - "$here/io.github.bbport.Launcher.desktop.in" \
    "$dest/io.github.bbport.Launcher.desktop" "$here/bb-launcher.sh" <<'PY'
import sys


def exec_path(path):
    """Quote a path for the desktop entry's Exec key (not shell quoting)."""
    path = path.replace("%", "%%")
    if not any(character.isspace() for character in path) and \
            not any(character in path for character in '"`$\\'):
        return path
    escaped = "".join("\\" + character if character in '"`$\\' else character
                      for character in path)
    return f'"{escaped}"'


template, target, launcher = sys.argv[1:]
with open(template, encoding="utf-8") as source:
    text = source.read()
with open(target, "w", encoding="utf-8") as destination:
    destination.write(text.replace("@LAUNCHER@", exec_path(launcher)))
PY
echo "Installed $dest/io.github.bbport.Launcher.desktop"
echo "Installed $icons/io.github.bbport.Launcher.png"
