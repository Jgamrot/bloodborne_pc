"""Run the separately downloaded BBSC BBport test package without leaving server settings behind.

This deliberately does not bundle BBSC or turn it on for normal launches. BBSC 0.0.1's
BBport wrapper is a test build; the author has not yet verified co-op on native BBport.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess


RELEASE_URL = "https://github.com/Classmg22/BBSC/releases/tag/v0.0.1"


class PreviewError(Exception):
    pass


def validate(package, port, game):
    package, port, game = Path(package).resolve(), Path(port).resolve(), Path(game).resolve()
    required = (
        package / "tools" / "play-bbport.ps1",
        package / "bbsc" / "bbsc-launch.exe",
        package / "bbsc" / "bbsc.dll",
        package / "bbsc" / "mod.json",
        port / "Bloodborne.exe",
        port / "bin" / "bb-probe.exe",
        game / "eboot.bin",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise PreviewError("Missing BBSC or BBport files:\n" + "\n".join(missing))
    try:
        manifest = json.loads((package / "bbsc" / "mod.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PreviewError(f"Could not read BBSC's mod.json: {error}") from error
    if manifest.get("id") != "bbsc" or "CUSA03173" not in manifest.get("games", []):
        raise PreviewError("The selected folder is not a BBSC package for CUSA03173.")
    return package, port, game


def _restore(path, original):
    if original is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(original)


def run_preview(package, port, game, *, runner=None):
    """Back up saves, run BBSC's own wrapper, then restore local launch configuration.

    ``runner`` is injectable so restoration can be checked without executing BBSC.
    Account information created by BBSC remains in its own package folder.
    """
    package, port, game = validate(package, port, game)
    user = port / "user"
    saves = user / "savedata"
    override = user / "host_overrides.custom.json"
    paths = package / "tools" / "bbport-paths.json"
    user.mkdir(parents=True, exist_ok=True)
    original_override = override.read_bytes() if override.exists() else None
    original_paths = paths.read_bytes() if paths.exists() else None

    backup = None
    if saves.is_dir():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = user / "bbsc-preview-backups" / stamp / "savedata"
        try:
            shutil.copytree(saves, backup)
        except OSError as error:
            raise PreviewError(f"Could not back up saves; BBSC was not started: {error}") from error

    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(package / "tools" / "play-bbport.ps1")]
    try:
        paths.write_text(json.dumps({"bbport": str(port / "Bloodborne.exe"),
                                     "eboot": str(game / "eboot.bin")}), encoding="utf-8")
        env = dict(os.environ)
        env["BB_USER_DIR"] = str(user)
        run = runner or subprocess.run
        result = run(command, cwd=package, env=env,
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0), check=False)
        return result.returncode, backup
    finally:
        try:
            _restore(override, original_override)
        finally:
            _restore(paths, original_paths)
