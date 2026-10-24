#!/usr/bin/env bash
# Builds dist/bbport-windows/ (and dist/bbport-windows.zip): Bloodborne.exe (the launcher, frozen
# with PyInstaller so players need no Python), bb-probe.exe with the MSYS2 CLANG64 DLLs it needs,
# the preparation scripts and run.py. Run from an MSYS2 CLANG64 shell after `bash build.sh`.
# Freezing uses a Windows Python 3.10+ (python.org; WINPYTHON overrides) and a private venv with
# PyInstaller and PySide6 Essentials. FSR 4 assets are included when present.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
source ./msys2-env.sh
[[ -f out/bb-probe.exe && -f out/bb-gpu-capabilities.exe && -f out/bb-play.exe ]] || { echo 'Build first: bash build.sh' >&2; exit 1; }

# A Windows Python (not MSYS2's) for PyInstaller.
python=${WINPYTHON:-}
if [[ -z $python ]]; then
    for candidate in /c/Python3*/python.exe "${LOCALAPPDATA:-/c/Users/$USER/AppData/Local}"/Programs/Python/Python3*/python.exe; do
        [[ -x $candidate ]] && python=$candidate
    done
fi
[[ -n $python ]] || { echo 'Need a Windows Python 3 (python.org) or WINPYTHON=path\to\python.exe' >&2; exit 1; }
# A venv outside Python's install tree may not find Tcl/Tk itself. Point PyInstaller's
# tkinter hook at the base interpreter's data so the frozen launcher keeps its UI.
for library in "$(dirname "$python")"/tcl/tcl*; do
    if [[ -d $library && -z ${TCL_LIBRARY:-} ]]; then export TCL_LIBRARY=$(cygpath -w "$library"); break; fi
done
for library in "$(dirname "$python")"/tcl/tk*; do
    if [[ -d $library && -z ${TK_LIBRARY:-} ]]; then export TK_LIBRARY=$(cygpath -w "$library"); break; fi
done
# Windows Python needs USERPROFILE (some MSYS2 shells start without it).
export USERPROFILE=${USERPROFILE:-$(cygpath -w "/c/Users/$(id -un)")}
venv=${BB_LAUNCHER_VENV:-out/qt-venv}
if [[ ! -x $venv/Scripts/python.exe ]]; then
    "$python" -m venv "$venv"
fi
# Qt Quick uses real translucent surfaces over full-window artwork. Pillow remains for the
# classic Tk fallback. Essentials avoids the unrelated, very large Qt Addons wheel.
"$venv/Scripts/python.exe" -m pip install -q --disable-pip-version-check pyinstaller pillow certifi PySide6_Essentials==6.12.0
# The scripts run inside Bloodborne.exe (--script): the standard modules they import come along.
hidden=()
for module in argparse base64 bisect collections contextlib hashlib json re shutil struct tempfile               xml.etree.ElementTree urllib.request ctypes.wintypes certifi; do
    hidden+=(--hidden-import "$module")
done
# The repository root: run.py is built in for the launcher's missing-files check (START_SCRIPTS).
"$venv/Scripts/python.exe" -m PyInstaller --noconfirm --clean --log-level WARN --windowed \
    --name Bloodborne --icon "$(cygpath -w "$PWD/launcher/assets/hunter-icon.ico")" --distpath out/pyi-dist \
    --workpath out/pyi-work --specpath out/pyi-work --paths "$(cygpath -w "$PWD/scripts")" \
    --paths "$(cygpath -w "$PWD")" "${hidden[@]}" \
    "$(cygpath -w "$PWD/launcher/bbport_launcher_win.py")"
# Qt Quick needs the VC runtime shipped with the PySide6 wheel. PyInstaller can pick an older
# root copy from Windows Python. It can also collect an unrelated ICU from the build host's PATH;
# that DLL shadows Windows' ICU and prevents Qt6Core from loading in the packaged launcher.
pyi_internal=out/pyi-dist/Bloodborne/_internal
for dll in VCRUNTIME140.dll VCRUNTIME140_1.dll; do
    cp "$pyi_internal/PySide6/$dll" "$pyi_internal/$dll"
done
rm -f "$pyi_internal/icuuc.dll" "$pyi_internal/icudt78.dll"

# The package is assembled in a fresh staging folder and zipped from there; dist/bbport-windows
# (a playable copy that may hold saves and settings) is only refreshed afterwards.
dest=out/stage/bbport-windows
rm -rf -- out/stage
mkdir -p "$dest/bin" "$dest/launcher"
cp -r out/pyi-dist/Bloodborne/. "$dest/"
llvm-strip -o "$dest/Play Bloodborne.exe" out/bb-play.exe
cp launcher/bloodborne.ico launcher/bloodborne.png "$dest/launcher/"
cp -r launcher/art "$dest/launcher/"
cp -r launcher/qml "$dest/launcher/"
mkdir -p "$dest/launcher/assets"
cp launcher/assets/hunter-icon.ico launcher/assets/hunter-icon.png "$dest/launcher/assets/"
cp -r launcher/assets/ui "$dest/launcher/assets/"
# ShadPs4Plus PKG Extractor 1.1 handles the user's own base and update PKGs from the
# launcher's Game page. Pin the upstream binary so release builds stay reproducible.
pkg_archive=out/vendor/ShadPs4Plus-PkgExtractor-1.1-windows.zip
pkg_url=https://github.com/AzaharPlus/shadPS4Plus/releases/download/PKG_EXTRACTOR_1_1/ShadPs4Plus-PkgExtractor-1.1-windows.zip
mkdir -p out/vendor
if [[ ! -f $pkg_archive ]]; then curl -fL --retry 3 "$pkg_url" -o "$pkg_archive"; fi
printf '%s  %s\n' 'a6a6dee84c1283949245c868e580ff8d0049d0e73df9de3096460ee26c6f04d7' "$pkg_archive" | sha256sum -c -
"$venv/Scripts/python.exe" - "$pkg_archive" "$dest/tools/pkg-extractor" <<'PY'
from pathlib import Path
import sys, zipfile

archive, destination = Path(sys.argv[1]), Path(sys.argv[2])
destination.mkdir(parents=True, exist_ok=True)
prefix = 'ShadPs4Plus-PkgExtractor-1.1-windows/'
with zipfile.ZipFile(archive) as source:
    for name in ('pkg_extractor.exe', 'libc++.dll', 'zlib1.dll'):
        (destination / name).write_bytes(source.read(prefix + name))
PY
# The executables without debug information (out/ keeps the symbols for crash reports).
for exe in bb-probe.exe bb-gpu-capabilities.exe; do
    llvm-strip --strip-debug -o "$dest/bin/$exe" "out/$exe"
done
# Every DLL the executables load from the CLANG64 tree (SDL3, FFmpeg, Vulkan loader, ...).
ldd "$dest/bin/bb-probe.exe" "$dest/bin/bb-gpu-capabilities.exe" |
    awk '/\/clang64\/bin\// {print $3}' | sort -u | while read -r dll; do
        cp -u "$dll" "$dest/bin/"
    done
cp -r scripts patches "$dest/"
# Hunter's Atlas (tools/atlas/README.md): its art and generator source, and the frozen generator
# (packaging/windows/build_atlas_generator.sh) when it was built.
mkdir -p "$dest/tools"
cp -r tools/atlas "$dest/tools/"
if [[ -x out/atlas-generator/generate_atlas.exe ]]; then
    cp -r out/atlas-generator "$dest/tools/atlas-generator"
else
    echo "Note: no out/atlas-generator (build_atlas_generator.sh): the package cannot prepare Hunter's Atlas maps" >&2
fi
# Discord Rich Presence (tools/bloodborne_rpc, by erezeth): built here from its source, shipped in
# companions/ and off until the player lists it in companions.json (run.py start_companions).
rpc="$dest/companions/Discord Rich Presence"
mkdir -p "$rpc"
clang++ -std=c++17 -O2 -DUNICODE -D_UNICODE -municode -mwindows -static \
    tools/bloodborne_rpc/main.cpp -o "$rpc/BloodborneRPC.exe" -lkernel32 -luser32
cp tools/bloodborne_rpc/companion.json tools/bloodborne_rpc/config.json "$rpc/"
# Button prompt mods (Xbox by Dommo, PCBButtons by JinkiJinn) are edits of the game's own
# menu/common.tpf.dcx, so they are not shipped: the launcher adds the player's own Nexus download.
# Legacy CPU (Intel 3rd generation and older): the translation plan scripts/cpu_compat.py applies.
mkdir -p "$dest/tools" && cp tools/legacy-cpu-plan.json "$dest/tools/"
cp run.py LICENSE README.md packaging/windows/README-Windows.txt "$dest/"
mkdir -p "$dest/docs"
cp -r docs/images "$dest/docs/"
if [[ -d fsr4_shaders ]]; then cp -r fsr4_shaders "$dest/"; fi
# Shader pre-build catalog (scripts/shader_catalog.py): records only, no game code or SPIR-V.
if [[ -d shader_catalog ]]; then cp -r shader_catalog "$dest/"; fi
# DLSS (NVIDIA RTX): the MSVC-built bridge and NVIDIA's runtime, next to bb-probe.exe
# (packaging/windows/build_dlss.sh). Without them the DLSS option stays unavailable.
if [[ -f out/bbport_dlss.dll && -f out/nvngx_dlss.dll ]]; then
    cp out/bbport_dlss.dll out/nvngx_dlss.dll "$dest/bin/"
    if [[ -f out/nvngx_dlssg.dll ]]; then cp out/nvngx_dlssg.dll "$dest/bin/"; fi
    mkdir -p "$dest/licenses" && cp out/NVIDIA-DLSS-LICENSE.txt "$dest/licenses/"
    cp gpu/dlss_bridge/LICENSE.txt "$dest/licenses/bbport_dlss-LICENSE.txt"
else
    echo "DLSS bridge not built (packaging/windows/build_dlss.sh): no DLSS in this package" >&2
fi
# Seamless co-op hosts: the shadNet server with the PS4-framing STUN fix
# (packaging/windows/build_coop_server.sh). Without it hosts use BBSC's own shadnet.exe.
if [[ -f out/coop-server/shadnet.exe ]]; then
    cp -r out/coop-server "$dest/bin/"
else
    echo "Co-op server not built (packaging/windows/build_coop_server.sh): hosts use BBSC's" >&2
fi
# Online co-op: the libraries compiled in (wepoll, cpp-httplib) and the MSYS2 DLLs it loads.
mkdir -p "$dest/licenses"
cp gpu/third_party/wepoll/LICENSE "$dest/licenses/wepoll-LICENSE.txt"
cp gpu/third_party/httplib/LICENSE "$dest/licenses/cpp-httplib-LICENSE.txt"
cp packaging/windows/licenses/*.txt "$dest/licenses/"
# Where The Hunter's Dream backend comes from (Awaken's port of bbhost's network code, GPL-3.0).
cp gpu/bbnet/THD-PORT.md "$dest/licenses/online-code-NOTICE.md"
cp gpu/bbnet/SHADNET-PORT.md "$dest/licenses/shadps4-network-NOTICE.md"
for package in protobuf abseil-cpp openssl miniupnpc zlib; do
    license=/clang64/share/licenses/$package/LICENSE
    if [[ -f $license ]]; then cp "$license" "$dest/licenses/$package-LICENSE.txt"; fi
done
find "$dest" -name __pycache__ -prune -exec rm -r {} +
# Nothing from the game itself may ship: its archives (.dcx and what they hold) and executables.
game_files=$(find "$dest" -type f \( -iname '*.dcx' -o -iname '*.tpf' -o -iname '*bnd' -o -iname '*.bdt' \
    -o -iname '*.bhd' -o -iname '*.prx' -o -iname '*.sprx' -o -iname 'eboot.bin' -o -iname 'param.sfo' \))
if [[ -n $game_files ]]; then
    echo "Game files in the package (players supply their own):" >&2
    echo "$game_files" >&2
    exit 1
fi
mkdir -p dist
rm -f dist/bbport-windows.zip
# Zip entries need forward slashes: Windows PowerShell's Compress-Archive writes backslashes,
# which other unzip tools (Linux, Proton) turn into flat files named "bbport-windows\_internal\..."
# (issue #75).
"$venv/Scripts/python.exe" - out/stage dist/bbport-windows.zip <<'PY'
from pathlib import Path
import sys, zipfile

stage, archive = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
    for path in sorted((stage / 'bbport-windows').rglob('*')):
        if path.is_file():
            package.write(path, path.relative_to(stage).as_posix())
PY

# Refresh dist/bbport-windows, keeping what players create there (saves, settings, mods), and
# only while nothing runs from it: deleting a running launcher's files breaks it.
play=dist/bbport-windows
running=$(powershell -NoProfile -Command \
    "@(Get-Process | Where-Object { \$_.Path -like '$(cygpath -w "$PWD/$play")\\*' }).Count" | tr -d '\r')
if [[ ${running:-0} != 0 ]]; then
    echo "dist/bbport-windows is in use ($running processes): not refreshed; the zip is ready." >&2
else
    mkdir -p "$play"
    find "$play" -mindepth 1 -maxdepth 1 ! -name user ! -name mods ! -name bbport.ini \
        ! -name mods.json ! -name patches.json -exec rm -rf {} +
    cp -r "$dest/." "$play/"
fi
du -sh "$dest" dist/bbport-windows.zip
