#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ${1:-} == --software ]]; then
    shift
    if [[ -z ${VK_DRIVER_FILES:-} ]]; then
        for candidate in /run/opengl-driver/share/vulkan/icd.d/lvp_icd*.json /usr/share/vulkan/icd.d/lvp_icd*.json; do
            if [[ -f $candidate ]]; then export VK_DRIVER_FILES=$candidate; break; fi
        done
    fi
    if [[ -z ${VK_DRIVER_FILES:-} ]]; then echo 'Lavapipe not found; set VK_DRIVER_FILES.' >&2; exit 1; fi
    export VK_LOADER_LAYERS_DISABLE='~implicit~'
fi
# BB_PREBUILT=1 (packaged builds, the AppImage): out/bb-probe and its GPU library are installed
# next to this script; nothing is built and no nix-shell is needed.
# BB_DATA_DIR: writable directory for the generated files (out/), saves (user/) and bbport.ini;
# by default this directory.
data=${BB_DATA_DIR:-.}
out=$data/out
mkdir -p "$out"
export BB_CONFIG=${BB_CONFIG:-$data/bbport.ini}
# FSR 4.1.1 assets (tools/fsr4cap/build_assets.sh): next to run.sh or in the data directory.
if [[ -z ${BB_FSR411_DIR:-} && ! -d fsr4_411 && -d $data/fsr4_411 ]]; then
    export BB_FSR411_DIR=$data/fsr4_411
fi
if [[ -z ${BB_PREBUILT:-} && -z ${BB_IN_NIX_SHELL:-} ]] && ! { command -v pkg-config >/dev/null && pkg-config --exists vulkan sdl3; } && command -v nix-shell >/dev/null; then
    args=''; if (( $# )); then args=$(printf '%q ' "$@"); fi
    exec env BB_IN_NIX_SHELL=1 nix-shell shell.nix --run "bash run.sh $args"
fi
if [[ -z ${PYTHON:-} ]]; then
    PYTHON=$(command -v python3 || true)
    if [[ -z $PYTHON ]]; then
        for candidate in /nix/store/*-python3-*/bin/python3; do
            if [[ -x $candidate ]]; then PYTHON=$candidate; break; fi
        done
    fi
fi
if [[ -z ${PYTHON:-} ]]; then echo 'Install Python 3 or set PYTHON.' >&2; exit 1; fi
# BB_GAME_DIR: the game's folder (eboot.bin, sce_module, ...); default next to this directory.
game=${BB_GAME_DIR:-../CUSA03173}
if [[ ! -f $game/eboot.bin ]]; then echo "No eboot.bin in $game (set BB_GAME_DIR)." >&2; exit 1; fi
original_game=$game
# Sizes chosen below for the previous launch are recomputed after an in-game restart.
if [[ ${BB_AUTO_RENDER_RES:-} == 1 ]]; then
    unset BB_RENDER_RES BB_OUTPUT_RES BB_AUTO_RENDER_RES
fi
# PC enhancements (bbport.ini pc_*, BB_PC_*): files made from the game, under the mods.
generated=()
enhancement_folders=()
# The in-game PC menu adds its rows only when its files were made, and the title's Quit Game
# only when both title movies have its line.
export BB_PC_MENU_ASSETS=0 BB_PC_MENU_QUIT=0 BB_PC_REBIRTH_ACTIVE=0
while IFS= read -r folder; do
    if [[ -n $folder ]]; then
        generated+=(--generated "$folder")
        enhancement_folders+=("$folder")
    fi
    [[ ${folder##*/} == rebirth ]] && BB_PC_REBIRTH_ACTIVE=1  # the altar's script is in place
    if [[ ${folder##*/} == pc-menu ]]; then
        BB_PC_MENU_ASSETS=1
        [[ -f $folder/dvdroot_ps4/menu/title.gfx && -f $folder/dvdroot_ps4/menu/title_dlc.gfx ]] && BB_PC_MENU_QUIT=1
    fi
done < <("$PYTHON" scripts/enhancements.py --game "$game" --out "$out/enhancements" --settings "$BB_CONFIG")
# The UI/movie viewport the renderer composes at (run.py exports the same): the widened HUD
# canvas for a patched ultrawide output, or the output size at another aspect ratio.
unset BB_UI_RES
hud_width=0 ui_width='' ui_height=''
# An explicit render size without an output size drives the scene only (run.py does the same):
# the game keeps its own output and movie viewport.
if [[ -z ${BB_RENDER_RES:-} || -n ${BB_OUTPUT_RES:-} ]]; then
    if read -r hud_width ui_width ui_height < <("$PYTHON" scripts/patches.py --print-ui-res \
            --settings "$BB_CONFIG" --output-res "${BB_OUTPUT_RES:-}" --game-dir "$original_game"); then
        if [[ -n ${ui_width:-} && -n ${ui_height:-} ]]; then
            export BB_UI_RES="${ui_width}x${ui_height}"
        fi
    fi
fi
# Ultrawide HUD layout (bbport.ini hud_position, 0 centred .. 100 edges): a layer above the
# generated enhancement files and below the player's mods, as run.py builds it.
if [[ ${hud_width:-0} =~ ^[0-9]+$ ]] && (( hud_width > 0 )); then
    position=100
    if [[ -f $BB_CONFIG ]]; then
        while IFS= read -r line || [[ -n $line ]]; do
            if [[ $line =~ ^[[:space:]]*hud_position[[:space:]]*=[[:space:]]*([0-9]+)[[:space:]]*$ ]]; then
                position=$((10#${BASH_REMATCH[1]}))
            fi
        done < "$BB_CONFIG"
    fi
    if (( position > 100 )); then position=100; fi
    if (( position >= 100 )); then
        position=1.0
    else
        printf -v position '0.%02d' "$position"
    fi
    "$PYTHON" -c 'import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$out/hud_layout"
    hud_args=(--out "$out/hud_layout" --canvas-width "$hud_width" --position "$position")
    for folder in ${enhancement_folders[@]+"${enhancement_folders[@]}"}; do
        hud_args+=(--source "$folder")
    done
    if ! "$PYTHON" scripts/hud_layout.py "$original_game" "${hud_args[@]}"; then
        echo 'HUD layout: failed; the HUD stays centred' >&2
    fi
    if [[ -d $out/hud_layout/dvdroot_ps4 ]]; then
        generated+=(--generated "$out/hud_layout")
    fi
fi
# The Xbox button prompts (seeded in mods/).
bundled=()
for folder in "mods/Xbox 360 Prompts (Elden Ring)"; do
    if [[ -d $folder ]]; then bundled=(--bundled "$folder"); break; fi
done
# The keyboard prompts (PCBButtons by JinkiJinn), seeded switched off.
for folder in "bundled/Keyboard Prompts (PCBButtons)"; do
    if [[ -d $folder ]]; then bundled+=(--bundled-off "$folder"); break; fi
done
game=$("$PYTHON" scripts/mods.py "$game" --out "$out" \
    --mods-dir "${BB_MODS_DIR:-$data/mods}" --config "${BB_MODS_CONFIG:-$data/mods.json}" \
    --enabled "${BB_MODS_ENABLED:-1}" ${generated[@]+"${generated[@]}"} ${bundled[@]+"${bundled[@]}"})
# Keyboard prompts: whether the key images are among the mods in use, as run.py does.
export BB_BUTTON_PROMPTS="" BB_KEY_PROMPT_IMAGES="0"
if [[ ${BB_MODS_ENABLED:-1} == 1 ]]; then
    if "$PYTHON" -c "import sys, pathlib; \
mods_dir = pathlib.Path(sys.argv[1]); \
cfg_path = pathlib.Path(sys.argv[2]); \
sys.path.insert(0, 'scripts'); \
import mods; \
sys.exit(0 if 'Keyboard Prompts (PCBButtons)' in mods.selected(mods_dir, cfg_path) else 1)" \
        "${BB_MODS_DIR:-$data/mods}" "${BB_MODS_CONFIG:-$data/mods.json}" 2>/dev/null; then
        export BB_BUTTON_PROMPTS="Keyboard"
        export BB_KEY_PROMPT_IMAGES="1"
    fi
fi
# A private merged view lasts for this launch, including restarts. Cleanup only our own view.
if [[ $game != "$(realpath "$original_game")" ]]; then
    mod_game=$game
    trap '"$PYTHON" -c '\''import shutil,sys; shutil.rmtree(sys.argv[1])'\'' "$mod_game"' EXIT
fi
"$PYTHON" scripts/prepare.py "$game" --out "$out"
"$PYTHON" scripts/link_libc.py "$game" --out "$out"
"$PYTHON" scripts/link_modules.py "$game" --out "$out"
# Legacy CPU profile (scripts/cpu_compat.py): bb-probe's CPU check lets such a CPU start.
if "$PYTHON" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("cpu_compat",{}).get("enabled") else 1)' "$out/link.json"; then
    export BB_CPU_COMPAT=1
else
    unset BB_CPU_COMPAT
fi
"$PYTHON" scripts/content_profile.py "$game" --out "$out" --sku "${BB_CONTENT_SKU:-full}"
# BB_RENDER_RES=WxH explicitly sets the game's render resolution (a patch at start).
# Frame rate: BB_FPS=uncap (default; delta-time patch, vblank follows the display),
# 60/90 (fixed-timestep patches) or 30 (unpatched). BB_PATCHES adds patch names ("a;b").
if [[ -f $BB_CONFIG ]]; then
    while IFS= read -r line || [[ -n $line ]]; do
        if [[ -z ${BB_FPS:-} && $line =~ ^[[:space:]]*fps_mode[[:space:]]*=[[:space:]]*([^[:space:]]+) ]]; then
            export BB_FPS=${BASH_REMATCH[1]}
        fi
        if [[ -z ${BB_FPS_LIMIT:-} && $line =~ ^[[:space:]]*fps_limit[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            limit=${BASH_REMATCH[1]}
            if (( limit > 0 )); then
                export BB_FPS_LIMIT=$limit
            fi
        fi
    done < "$BB_CONFIG"
fi
fps=${BB_FPS:-uncap}
# bbport.ini output_res other than 1080p (720p for the Steam Deck, 1440p, 2160p): the whole game
# renders at the preset's size of the output (a patch), the upscaler fills the output, the UI is
# drawn at the output size. Preset and output changes need a restart.
# Live resolution changes keep the guest at 1920x1080 and scale host targets at run time instead
# (output and presets change in the menu without a restart, but post-processing stays at 1080p
# and scene targets are copied back: much slower on the Steam Deck and older GPUs). Chosen by
# BB_LIVE_RES=0/1, else bbport.ini live_resolution=0/1/auto (auto: the GPU check, strong
# discrete GPUs get them); off when unset. 1080p output and TAA always use the live path.
if [[ -z ${BB_RENDER_RES:-} ]]; then
    read -r scaled_render scaled_output < <("$PYTHON" scripts/patches.py --print-scaled --settings "$BB_CONFIG") || true
fi
live=0
if [[ -n ${scaled_output:-} ]]; then
    live=${BB_LIVE_RES:-}
    # Bash builtins only: the AppImage's PATH has no sed/grep (a missing one ended run.sh silently).
    if [[ -z $live && -f $BB_CONFIG ]]; then
        while IFS= read -r line || [[ -n $line ]]; do
            [[ $line =~ ^live_resolution=([01]|auto)$ ]] && live=${BASH_REMATCH[1]}
        done < "$BB_CONFIG"
    fi
    if [[ $live == auto ]]; then
        if [[ -n ${BB_PROBE:-} ]]; then caps=$(dirname -- "$BB_PROBE")/bb-gpu-capabilities
        elif [[ -n ${BB_PREBUILT:-} ]]; then caps=bin/bb-gpu-capabilities
        else caps=out/bb-gpu-capabilities; fi
        live=$("$caps" --live-resolution 2> >(while IFS= read -r line; do
            [[ $line == *MANGOHUD* ]] || printf '%s\n' "$line"; done >&2)) || live=0
    fi
    [[ $live == 1 ]] || live=0
fi
if [[ $live == 1 ]]; then
    echo "Output ${scaled_output}: live resolution changes (live_resolution=0: startup patch)"
elif [[ -n ${scaled_output:-} ]]; then
    export BB_RENDER_RES=$scaled_render BB_OUTPUT_RES=$scaled_output BB_AUTO_RENDER_RES=1
    export BB_DMEM_MB=${BB_DMEM_MB:-9152}
    echo "Output ${scaled_output}: scene ${scaled_render}, direct memory ${BB_DMEM_MB} MiB (live_resolution=1: live changes)"
fi
"$PYTHON" scripts/patches.py --out "$out" --fps "$fps" --extra "${BB_PATCHES:-}" --settings "$BB_CONFIG" --game-dir "$game" --render-res "${BB_RENDER_RES:-}" --output-res "${BB_OUTPUT_RES:-}" \
    --patches-dir "${BB_PATCHES_DIR:-$data/patches}" --patches-config "${BB_PATCHES_CONFIG:-$data/patches.json}"
if [[ -z ${BB_VBLANK_HZ:-} ]]; then
    case $fps in uncap) export BB_VBLANK_HZ=0 ;; 90) export BB_VBLANK_HZ=90 ;; *) export BB_VBLANK_HZ=60 ;; esac
fi
# FSR 4: faster post passes next to the downloaded ones (incremental; tools/fsr4_optimize.sh).
if [[ -z ${BB_PREBUILT:-} && -d fsr4_shaders ]] && command -v spirv-cross >/dev/null; then
    bash tools/fsr4_optimize.sh || echo 'FSR 4: optimized post passes not built' >&2
fi
if [[ -n ${BB_PREBUILT:-} ]]; then
    probe=${BB_PROBE:-bin/bb-probe}
else
    bash build.sh
    probe=out/bb-probe
fi
probe_args=("$out/boot-linked.bin" --content-profile "$out/content.bin" --patches "$out/patches.bin" --app0 "$game" --user "${BB_USER_DIR:-$data/user}" --timeout "${BB_TIMEOUT:-0}" "$@")
if [[ -n ${mod_game:-} ]]; then
    "$probe" "${probe_args[@]}" &
    mod_pid=$!
    trap 'kill -TERM "$mod_pid" 2>/dev/null || true' TERM INT
    mod_status=0
    wait "$mod_pid" || mod_status=$?
    # An interrupted wait must finish the child before removing its mounted view.
    if kill -0 "$mod_pid" 2>/dev/null; then wait "$mod_pid" || mod_status=$?; fi
    exit "$mod_status"
fi
exec "$probe" "${probe_args[@]}"
