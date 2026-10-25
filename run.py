#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows counterpart of run.sh: prepares the game image and starts bb-probe.exe.

Same environment variables as run.sh (BB_GAME_DIR, BB_DATA_DIR, BB_FPS, BB_RENDER_RES,
BB_LIVE_RES, BB_PATCHES, BB_MODS_*, BB_USER_DIR, ...). Extra arguments go to bb-probe.
The in-game "Apply and restart" runs this script again through BB_RESTART_COMMAND;
`--after PID` waits for the previous game process to end first (its GPU device and memory).
"""
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

PORT = Path(__file__).resolve().parent
# The keyboard key images (PCBButtons from Nexus Mods), as the launcher adds them to the mods
# folder (launcher KEYBOARD_PROMPTS).
KEYBOARD_PROMPTS = 'Keyboard Prompts (PCBButtons)'


# Co-op: the community service that answers Bloodborne's own game-server requests
# (messages, bloodstains, summon signs, sign-in).
COMMUNITY_SERVER = 'https://thehuntersdream.com'
GAME_SERVER = 'https://ss4.scej-network.jp:20443'
# The server's ss.info sends the game to this port for its API (summons among them).
COMMUNITY_API_PORT = 18671


def online_overrides(env, user_dir):
    """Writes user/host_overrides.json for this launch. A player who needs other addresses
    puts them in user/host_overrides.custom.json, which is then used as it is. A launch that
    brings its own (BB_HOST_OVERRIDES: seamless co-op, pointed at the host's servers) uses that
    file for this launch only."""
    custom = Path(env['BB_HOST_OVERRIDES']) if env.get('BB_HOST_OVERRIDES') else         user_dir / 'host_overrides.custom.json'
    path = custom if custom.exists() else user_dir / 'host_overrides.json'
    if path != custom:
        community = (env.get('BB_COMMUNITY_SERVER') or COMMUNITY_SERVER).rstrip('/')
        if '://' not in community:
            community = 'https://' + community
        scheme, host = community.split('://', 1)
        # The game's own server functions (messages, bloodstains, summon signs) go over HTTP to
        # the game server only, as bbhost and Awaken's port send them; never through a shadNet
        # WebAPI (Metr1k, The Hunter's Dream). Play logs go to its API port instead of
        # FromSoftware's old storage buckets.
        overrides = {GAME_SERVER: community}
        overrides.update({f'https://{bucket}:443': f'{scheme}://{host}:{COMMUNITY_API_PORT}'
                          for bucket in PLAY_LOG_HOSTS})
        print(f'Co-op: game server {community}')
        path.write_text(json.dumps(overrides, indent=2) + '\n', encoding='utf-8')
    env['SHADPS4_HTTP_HOST_OVERRIDES_JSON'] = str(path)


# The Hunter's Dream co-op pool (BB_NET_BACKEND=thd, with bbhost players): the engine's own
# backend for it (gpu/bbnet/thd, bbhost's protocol, from Awaken's port). The game's servers and
# play logs go to the game server over HTTP; the account comes from the launcher's Discord sign-in.
PLAY_LOG_HOSTS = ('bb-playlog-prod.s3.amazonaws.com', 'bb-playlog-test.s3.amazonaws.com')
THD_ENV = ('BB_NET_BACKEND', 'BB_THD_TOKEN', 'BB_THD_ONLINE_ID', 'BB_THD_SERVER', 'BB_THD_AUTH',
           'BB_THD_RULESET')


def hunters_dream(env, user_dir):
    if not env.get('BB_THD_TOKEN') or not env.get('BB_THD_ONLINE_ID'):
        fail("The Hunter's Dream: not signed in. Sign in with Discord on the launcher's Online page.")
    community = (env.get('BB_COMMUNITY_SERVER') or COMMUNITY_SERVER).rstrip('/')
    if '://' not in community:
        community = 'https://' + community
    base = community
    overrides = {'*.scej-network.jp': base}
    overrides.update({host: f'{base}:{COMMUNITY_API_PORT}' for host in PLAY_LOG_HOSTS})
    path = user_dir / 'host_overrides.json'
    path.write_text(json.dumps(overrides, indent=2) + '\n', encoding='utf-8')
    for key in ('BB_SHADNET_SERVER', 'BB_SHADNET_WEBAPI', 'BB_SHADNET_NPID', 'BB_SHADNET_PASSWORD',
                'BB_SHADNET_TOKEN'):
        env.pop(key, None)
    env.update(SHADPS4_HTTP_HOST_OVERRIDES_JSON=str(path), BB_THD_SERVER=f'{base}:{COMMUNITY_API_PORT}',
               BB_THD_AUTH=base)
    env.setdefault('BB_THD_RULESET', 'vanilla')
    env.setdefault('BB_P2P_PORT', '3658')
    env.setdefault('BB_SIGN_TIMEOUT', '30')
    print(f"Co-op: The Hunter's Dream as {env['BB_THD_ONLINE_ID']} ({base})")


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


# The scripts a start runs or imports. A copy of the port with some left out (seen in repacks
# from other sites, GitHub issue #118) stopped with "No module named 'game_check'"; it now says
# what is missing and where the whole package is. (After Awaken's port 0.9.30: "a game folder
# missing its core files now gets a clear message instead of crashing".)
START_SCRIPTS = ('game_check.py', 'enhancements.py', 'atlas.py', 'patches.py', 'aspect_ratio.py', 'mods.py',
                 'language_files.py', 'hud_layout.py', 'content_profile.py', 'link_libc.py', 'link_modules.py',
                 'prepare.py', 'shader_code.py', 'quiet_output.py')
RELEASES = 'https://github.com/Jgamrot/bloodborne_pc/releases/latest'
# Text languages (PS4 system language ids) the game shows without Unlock Game Region: English
# (US) and Russian (GitHub issue #58: Russian text without it).
REGION_LANGUAGES = ('', '1', '8')


def missing_port_files(port=None):
    port = port or PORT
    return [f'scripts\\{name}' for name in START_SCRIPTS if not (port / 'scripts' / name).is_file()]


def explain_missing_port_files(missing):
    more = f' and {len(missing) - 1} more' if len(missing) > 1 else ''
    return (f'This copy of the port is incomplete: {missing[0]}{more} missing from {PORT}. '
            f'Download the port again from {RELEASES} and unpack the whole zip; copies from '
            f'other sites often leave files out.')


def wait_for(pid):
    kernel32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        kernel32.WaitForSingleObject(handle, 30000)
        kernel32.CloseHandle(handle)


def no_console():
    """Started without a console (the launcher): console programs must not open their own."""
    return 0 if ctypes.windll.kernel32.GetConsoleWindow() else subprocess.CREATE_NO_WINDOW


def run_script(name, *args, capture=False, optional=False):
    """Its output when captured ('' otherwise). A failure stops the start, unless the script is
    `optional` (it only adds to the game): that is logged, and the result is None."""
    # Inside the packaged Bloodborne.exe (PyInstaller) the executable runs scripts itself.
    script = ['--script'] if getattr(sys, 'frozen', False) else []
    command = [sys.executable, *script, str(PORT / 'scripts' / name), *map(str, args)]
    if capture:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True,
                                creationflags=no_console())
    else:
        # stdin given: the output handles are passed explicitly (a windowed Bloodborne.exe child
        # would get none otherwise).
        result = subprocess.run(command, stdin=subprocess.DEVNULL, creationflags=no_console())
    if result.returncode:
        if not optional:
            sys.exit(result.returncode)
        print(f'{name} failed (exit code {result.returncode}); starting without it', file=sys.stderr)
        return None
    return result.stdout if capture else ''


def auto_live_blurs_dof(output, config):
    """live_resolution=auto keeps the startup patch for outputs above 1080p with depth of field on:
    the live path renders such scenes into host targets larger than the guest's 1920x1080, and
    the game's depth of field composite, built for its own half-resolution targets, blurs them
    (Native at 4K came out softer than Performance). From emurphy04 (Supermedo PR #75)."""
    width, height = (int(v) for v in output.split('x'))
    return (width > 1920 or height > 1080) and ini_value(config, 'effect_dof') != '0'


def ini_value(path, key):
    try:
        for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.fullmatch(rf'{re.escape(key)}=(.*)', line.strip())
            if match:
                return match.group(1)
    except OSError:
        pass
    return None


def find_executable(name):
    """bin/ (packaged), else out/ (built with build.sh)."""
    for candidate in (PORT / 'bin' / name, PORT / 'out' / name):
        if candidate.is_file():
            return candidate
    return None


def shader_prebuild(game, out, env):
    """Shader pre-build (vk_shader_prebuild.h): the game's shader code, extracted from the
    player's own files into out/shader_code once (again only when those files or the
    extractor change), lets the game translate the shaders its cache and the shipped catalog
    know before they are first drawn. BB_SHADER_PREBUILD=0 turns it off."""
    if env.get('BB_SHADER_PREBUILD') == '0':
        return
    code = out / 'shader_code'
    sources = sorted((Path(game) / 'dvdroot_ps4' / 'shader').glob('*.shaderbnd*.dcx'))
    sources.append(out / 'eboot.elf')
    sources.append(PORT / 'scripts' / 'shader_code.py')
    stamp = '\n'.join(f'{p.name} {p.stat().st_size} {int(p.stat().st_mtime)}' for p in sources if p.is_file())
    try:
        current = (code / 'stamp.txt').read_text(encoding='utf-8') == stamp
    except OSError:
        current = False
    if not current:
        shutil.rmtree(code, ignore_errors=True)
        if run_script('shader_code.py', game, out / 'eboot.elf', code, optional=True) is None:
            shutil.rmtree(code, ignore_errors=True)  # shaders are then translated in game
            return
        (code / 'stamp.txt').write_text(stamp, encoding='utf-8')
    env['BB_SHADER_CODE'] = str(code)
    catalog = PORT / 'shader_catalog'
    if catalog.is_dir():
        env['BB_SHADER_CATALOG'] = str(catalog)


# Low-VRAM profile (from a player's 4 GB mod; ethan, Supermedo 44a6433; measured on an RTX 3050 Ti
# Laptop, i5-11300H, Central Yharnam, 1080p output with an upscaler): the texture cache's own marks
# had it evict and upload again ~30 textures a second with 2.7 GB in use, and the live path's
# native-size game targets cost ~700 MiB more than the startup patch (2.8 GB at 640x360 against
# 2.1 GB at 960x540). Discrete GPUs up to LOW_VRAM_MB; BB_LOW_VRAM=1 forces the profile, 0 turns
# it off.
LOW_VRAM_MB = 4608
# Left to the desktop, browsers and the driver.
VRAM_RESERVE_MB = 600


def low_vram_mb(env, caps):
    """The card's memory in MiB when the low-VRAM profile applies, else 0. caps is
    bb-gpu-capabilities, which picks the GPU the game uses (BB_GPU_ID included)."""
    setting = env.get('BB_LOW_VRAM', '')
    if setting == '0':
        return 0
    vram, discrete = 0, False
    try:
        result = subprocess.run([str(caps), '--vram'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=20, creationflags=no_console())
        size, kind = result.stdout.split()
        vram, discrete = int(size), kind == '1'
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if setting == '1':
        return vram or 4096
    # Integrated GPUs follow the driver's budget already (texture_cache.cpp).
    return vram if discrete and 0 < vram <= LOW_VRAM_MB else 0


def physical_cores():
    """CPU cores, not threads (GetLogicalProcessorInformation); os.cpu_count() when unknown."""
    try:
        from ctypes import wintypes
        size = wintypes.DWORD(0)
        ctypes.windll.kernel32.GetLogicalProcessorInformation(None, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not ctypes.windll.kernel32.GetLogicalProcessorInformation(buffer, ctypes.byref(size)):
            raise OSError
        # SYSTEM_LOGICAL_PROCESSOR_INFORMATION: ULONG_PTR mask, then the relationship (0 = a core).
        entry = ctypes.sizeof(ctypes.c_void_p) * 2 + 16
        cores = sum(1 for offset in range(0, size.value - entry + 1, entry)
                    if int.from_bytes(buffer.raw[offset + ctypes.sizeof(ctypes.c_void_p):][:4], 'little') == 0)
        if cores:
            return cores
    except (AttributeError, OSError):
        pass
    return os.cpu_count() or 8


def start_companions(data, env, game_pid):
    """Companions (tools/bloodborne_rpc: Discord Rich Presence): programs in <data>/companions/<name>/
    that run beside the game, each started only when companions.json lists its folder name under
    "enabled" (none by default). companion.json names the program; it gets the game's process id
    in BB_GAME_PID. They end with the game."""
    started = []
    try:
        enabled = set(json.loads((data / 'companions.json').read_text(encoding='utf-8')).get('enabled', []))
    except (OSError, ValueError):
        return started
    companions = data / 'companions'
    for folder in sorted(companions.iterdir() if companions.is_dir() else ()):
        if not folder.is_dir() or folder.name not in enabled:
            continue
        try:
            spec = json.loads((folder / 'companion.json').read_text(encoding='utf-8'))
            exe = folder / spec.get('exe', '')
            if not exe.is_file() or exe.suffix.lower() != '.exe':
                continue
            print(f'Companion: {spec.get("name", folder.name)}')
            started.append(subprocess.Popen([str(exe)], cwd=folder, env={**env, 'BB_GAME_PID': str(game_pid)},
                                            stdin=subprocess.DEVNULL, creationflags=no_console()))
        except (OSError, ValueError) as error:
            print(f'Companion {folder.name} not started: {error}', file=sys.stderr)
    return started


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == '--after':
        wait_for(int(args[1]))
        args = args[2:]
    # As run.sh: relative paths (BB_GAME_DIR, BB_DATA_DIR, fsr4_shaders/) are from the port.
    os.chdir(PORT)
    if missing := missing_port_files():
        fail(explain_missing_port_files(missing))
    env = os.environ
    data = Path(env.get('BB_DATA_DIR', PORT))
    out = data / 'out'
    out.mkdir(parents=True, exist_ok=True)
    env.setdefault('BB_CONFIG', str(data / 'bbport.ini'))
    config = env['BB_CONFIG']
    if not env.get('BB_FSR411_DIR') and not (PORT / 'fsr4_411').is_dir() and (data / 'fsr4_411').is_dir():
        env['BB_FSR411_DIR'] = str(data / 'fsr4_411')

    probe = Path(env['BB_PROBE']) if env.get('BB_PROBE') else find_executable('bb-probe.exe')
    if not probe or not probe.is_file():
        fail('bb-probe.exe not found: build it with build.sh (MSYS2 CLANG64) or use a packaged build.')
    # Development builds run from the MSYS2 tree: its CLANG64 DLLs (SDL3, FFmpeg, ...).
    if not (probe.parent / 'SDL3.dll').is_file():
        clang64 = Path(env.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64' / 'bin'
        if clang64.is_dir():
            env['PATH'] = f'{clang64}{os.pathsep}{env.get("PATH", "")}'

    game = Path(env.get('BB_GAME_DIR', PORT.parent / 'CUSA03173'))
    if not (game / 'eboot.bin').is_file():
        fail(f'No eboot.bin in {game} (set BB_GAME_DIR).')
    original_game = game.resolve()
    # A broken extraction (stale compressed sectors): the game would hang loading its shaders,
    # with no error. (parsifal295, Supermedo PR #64; bbport 0.5-pre4.) BB_SKIP_GAME_CHECK=1 skips it.
    if env.get('BB_SKIP_GAME_CHECK') != '1':
        sys.path.insert(0, str(PORT / 'scripts'))
        import game_check
        if broken := game_check.broken_files(game):
            fail(game_check.explain(broken))
    # PC enhancements (bbport.ini pc_*, BB_PC_*): files made from the game, under the mods.
    # Optional: should they fail, the game starts as without them.
    generated = (run_script('enhancements.py', '--game', game, '--out', Path(out) / 'enhancements',
                            '--settings', config, capture=True, optional=True) or '').splitlines()
    # The in-game PC menu adds its rows only when its sections and strings were made, and the
    # title's Quit Game only when both title movies have its line.
    menu = next((Path(folder) for folder in generated if Path(folder).name == 'pc-menu'), None)
    env['BB_PC_MENU_ASSETS'] = '1' if menu else '0'
    # Hunter's Atlas (bbport.ini atlas_enabled, scripts/atlas.py): the map's files, prepared once
    # from the game by the launcher, in the data folder.
    sys.path.insert(0, str(PORT / 'scripts'))
    import atlas
    from patches import read_settings
    for key in [k for k in env if k.startswith(('BB_MAP_', 'BB_ATLAS_'))]:
        del env[key]
    atlas_env = atlas.environment(read_settings(Path(config)), Path(env.get('BB_ATLAS_DIR', data / 'atlas')))
    env.update(atlas_env)
    if atlas_env:
        print(f"Hunter's Atlas: on (maps in {atlas_env['BB_MAP_DIR']})")
    elif ini_value(config, 'atlas_enabled') == '1':
        print("Hunter's Atlas: on in the settings, but its maps are not prepared (launcher: Prepare maps)")
    # Rebirth's runtime half acts only with the altar's rewritten script in place.
    env['BB_PC_REBIRTH_ACTIVE'] = '1' if any(Path(f).name == 'rebirth' for f in generated) else '0'
    env['BB_PC_MENU_QUIT'] = '1' if menu and all(
        (menu / 'dvdroot_ps4/menu' / name).is_file() for name in ('title.gfx', 'title_dlc.gfx')) else '0'
    # Ultrawide outputs (wider than 16:9): the menu movies with full-screen backdrops widened and
    # the HUD's corner groups toward the screen edges (bbport.ini hud_position, 0 centred .. 100
    # edges), a layer above the generated ones (it builds on their menu movies) and below the
    # mods. Only for the 01.09 game, whose camera and HUD canvas patches.py widens (hud_canvas).
    # From emurphy04 (Supermedo/bloodborne_pc PR #70).
    sys.path.insert(0, str(PORT / 'scripts'))
    from patches import OUTPUT_SIZE, eboot_is_109, game_app_version, hud_canvas, output_size
    hud_layer = Path(out) / 'hud_layout'
    shutil.rmtree(hud_layer, ignore_errors=True)
    output_res = env.get('BB_OUTPUT_RES') or ini_value(config, 'output_res') or ''
    canvas = hud_canvas(output_size({'output_res': output_res}))
    # Only for the clean 1.09 eboot.bin: patches.py leaves a modified one unpatched (16:9), and
    # widened menus on a 16:9 game came out stretched (Supermedo PR #90, emurphy04).
    clean = game_app_version(game) in (None, '01.09') and eboot_is_109(str(Path(game).resolve() / 'eboot.bin'))
    if canvas != OUTPUT_SIZE and (clean or env.get('BB_FORCE_PATCHES')):
        position = ini_value(config, 'hud_position') or '100'
        position = max(0, min(100, int(position) if position.isdigit() else 100)) / 100
        run_script('hud_layout.py', game, '--out', hud_layer, '--canvas-width', canvas[0],
                   '--position', position, *(arg for folder in generated for arg in ('--source', folder)),
                   optional=True)
        if (hud_layer / 'dvdroot_ps4').is_dir():
            generated.append(str(hud_layer))
    # Text and voice languages (scripts/language_files.py): Brazilian Portuguese text from the
    # game's porbr files, and the voice language apart from the text's (BB_VOICE_LANGUAGE).
    # BB_LANGUAGE_FILES=0: the game's own choice. (After Berleis, Supermedo PR #20.)
    language_layer = Path(out) / 'language'
    voice = env.get('BB_VOICE_LANGUAGE') or ini_value(config, 'voice_language') or ''
    if env.get('BB_LANGUAGE_FILES') != '0':
        run_script('language_files.py', game, '--out', language_layer, '--language', env.get('BB_LANGUAGE', ''),
                   '--voice', voice, optional=True)
        if (language_layer / 'dvdroot_ps4').is_dir():
            generated.append(str(language_layer))
    game = Path(run_script('mods.py', game, '--out', out,
                           '--mods-dir', env.get('BB_MODS_DIR', data / 'mods'),
                           '--config', env.get('BB_MODS_CONFIG', data / 'mods.json'),
                           '--enabled', env.get('BB_MODS_ENABLED', '1'),
                           *(arg for folder in generated for arg in ('--generated', folder)),
                           capture=True).strip())
    mod_view = game if game.resolve() != original_game else None
    # Keyboard prompts: whether the key images are among the mods in use, as the launcher's
    # Controller page or the overlay's Mods tab left mods.json (read again on an in-game restart).
    # src/key_prompts.c names the bound keys in text when the images do not match the bindings.
    keyboard = False
    if env.get('BB_MODS_ENABLED', '1') == '1':
        sys.path.insert(0, str(PORT / 'scripts'))
        import mods as mod_list
        try:
            keyboard = KEYBOARD_PROMPTS in mod_list.selected(Path(env.get('BB_MODS_DIR', data / 'mods')),
                                                           Path(env.get('BB_MODS_CONFIG', data / 'mods.json')))
        except (OSError, ValueError):
            pass
    env['BB_BUTTON_PROMPTS'] = 'Keyboard' if keyboard else ''
    env['BB_KEY_PROMPT_IMAGES'] = '1' if keyboard else '0'
    try:
        run_script('prepare.py', game, '--out', out)
        sys.path.insert(0, str(PORT / 'scripts'))
        from aspect_ratio import segment_fingerprint
        env['BB_ASPECT_EBOOT_SEGMENTS'] = segment_fingerprint((out / 'eboot.elf').read_bytes())
        shader_prebuild(game, out, env)
        run_script('link_libc.py', game, '--out', out)
        run_script('link_modules.py', game, '--out', out)
        # Legacy CPU profile (scripts/cpu_compat.py): the image no longer needs BMI1, LZCNT or
        # MOVBE, and bb-probe's CPU check lets such a CPU start.
        try:
            compat = json.loads((out / 'link.json').read_text(encoding='utf-8')).get('cpu_compat', {})
        except (OSError, ValueError):
            compat = {}
        if compat.get('enabled'):
            env['BB_CPU_COMPAT'] = '1'
        else:
            env.pop('BB_CPU_COMPAT', None)
        run_script('content_profile.py', game, '--out', out, '--sku', env.get('BB_CONTENT_SKU', 'full'))

        # Patches exist for game version 01.09 only (patches.py applies none to others): other
        # versions keep the game's 30 FPS timing and change resolutions live.
        sys.path.insert(0, str(PORT / 'scripts'))
        from patches import eboot_matches_patches, game_app_version
        version = game_app_version(game)
        forced = bool(env.get('BB_FORCE_PATCHES'))
        patched = version in (None, '01.09') or forced
        if not patched:
            print(f'Game version {version}: community patches need 01.09; 30 FPS, no effect patches')
        elif not forced and not eboot_matches_patches(out / 'eboot.elf'):
            # param.sfo says 01.09, the code is another build's: the patches would break it.
            patched = False
            print('Game files: eboot.bin is not the 01.09 build the community patches were made for; '
                  '30 FPS, no effect patches')
        # Sizes chosen below for the previous launch are recomputed after an in-game restart.
        if env.get('BB_AUTO_RENDER_RES') == '1':
            for key in ('BB_RENDER_RES', 'BB_OUTPUT_RES', 'BB_AUTO_RENDER_RES'):
                env.pop(key, None)
        fps = env.get('BB_FPS', 'uncap') if patched else '30'
        scaled_render = scaled_output = None
        if not env.get('BB_RENDER_RES'):
            printed = run_script('patches.py', '--print-scaled', '--settings', config, capture=True).split()
            if len(printed) == 2:
                scaled_render, scaled_output = printed
        live = '0'
        if scaled_output:
            live = env.get('BB_LIVE_RES') or ini_value(config, 'live_resolution') or '0'
            if live == 'auto' and auto_live_blurs_dof(scaled_output, config):
                live = '0'
                print(f'Output {scaled_output}: live resolution auto: startup patch (depth of field '
                      'blurs live scenes above 1080p; live_resolution=1 forces live changes)')
            if live == 'auto':
                caps = probe.parent / 'bb-gpu-capabilities.exe'
                live = '0'  # without the checker, the safe answer: no live changes
                if caps.is_file():
                    result = subprocess.run([str(caps), '--live-resolution'], stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, text=True, creationflags=no_console())
                    live = result.stdout.strip() if result.returncode == 0 else '0'
            live = '1' if live == '1' or not patched else '0'
        from patches import hud_canvas, is_16_9, ultrawide
        env.pop('BB_ASPECT_PATCHED', None)
        if scaled_output or env.get('BB_OUTPUT_RES'):
            movie_output = scaled_output or env['BB_OUTPUT_RES']
            ow, oh = map(int, movie_output.split('x'))
            if patched and ultrawide((ow, oh)):
                # Kyo's 21:9 patch for this aspect ratio (patches.py ultrawide_writes): camera,
                # HUD canvas and markers at start, so no live changes and no camera hook.
                live = '0'
                canvas = hud_canvas((ow, oh))
                env['BB_UI_RES'] = f'{canvas[0]}x{canvas[1]}'
                env['BB_ASPECT_PATCHED'] = '1'
                print(f'Output {movie_output}: ultrawide, HUD {env["BB_UI_RES"]}; aspect changes require restart')
            elif not is_16_9((ow, oh)):
                live = '0'
                env['BB_UI_RES'] = movie_output
                print('Aspect correction: centered 16:9 stage; aspect changes require restart')
            else:
                env.pop('BB_UI_RES', None)
        else:
            env.pop('BB_UI_RES', None)
        if live == '1':
            print(f'Output {scaled_output}: live resolution changes (live_resolution=0: startup patch)')
        elif scaled_output:
            env.update(BB_RENDER_RES=scaled_render, BB_OUTPUT_RES=scaled_output, BB_AUTO_RENDER_RES='1')
            env.setdefault('BB_DMEM_MB', '9152')
            print(f'Output {scaled_output}: scene {scaled_render}, direct memory {env["BB_DMEM_MB"]} MiB '
                  '(live_resolution=1: live changes)')
        vram = low_vram_mb(env, probe.parent / 'bb-gpu-capabilities.exe')
        if vram:
            env.setdefault('BB_GC_BUDGET_MB', str(max(2048, vram - VRAM_RESERVE_MB)))
            notes = [f'texture budget {env["BB_GC_BUDGET_MB"]} MiB']
            # At 1080p output the live path keeps the game's targets native; here they shrink too.
            wants_live = (env.get('BB_LIVE_RES') or ini_value(config, 'live_resolution')) == '1'
            if (patched and not scaled_output and not env.get('BB_RENDER_RES') and not wants_live
                    and ini_value(config, 'upscaler') != 'taa'):
                size = run_script('patches.py', '--print-preset-size', '--settings', config, capture=True).strip()
                if size:
                    env.update(BB_RENDER_RES=size, BB_AUTO_RENDER_RES='1')
                    notes.append(f'scene {size} patched at start (live_resolution=1: live changes)')
                    # On this path most prepared draws go unused (145494 of 182272), and on four
                    # cores the workers take time from the game: 53.0 FPS with 4 workers, 55.1
                    # with 2, 56.8 without (minimum 45.3, 48.4, 53.3; i5-11300H, 4 cores, 8
                    # threads). On 8 cores the workers win: 197 FPS without them, 234 with 4.
                    if physical_cores() <= 4 and 'BB_PREP_WORKERS' not in env:
                        env['BB_PREP_WORKERS'] = '0'
                        notes.append('no draw-preparation workers')
            print(f'Low-VRAM profile ({vram} MiB card): {", ".join(notes)}; BB_LOW_VRAM=0 turns it off')
        # The game's graphics heaps at PC sizes need the larger pool (patches.py HEAP_PATCH;
        # pc_heaps=0 / BB_PC_HEAPS=0: the PS4's heaps, the larger pool only above 1080p).
        if patched and (env.get('BB_PC_HEAPS') or ini_value(config, 'pc_heaps') or '1') != '0':
            env.setdefault('BB_DMEM_MB', '9152')
        # Frame limiter slots on the planned grid (driver.cpp, Supermedo d646b1d); off by default.
        if not env.get('BB_FRAME_CAP_GRID') and ini_value(config, 'frame_cap_grid') == '1':
            env['BB_FRAME_CAP_GRID'] = '1'
        extra = env.get('BB_PATCHES', '')
        # The game shows only its region's text languages and falls back to English for the
        # others: Chinese (BB_LANGUAGE 10, 11), and Spanish and Japanese too (GitHub issues #126,
        # #133; Spanish checked in game). Every language but English and Russian (shown without
        # it) gets the region unlocked (k1m0206, Supermedo PR #91; its server lookups stay on
        # Europe).
        if env.get('BB_LANGUAGE', '1') not in REGION_LANGUAGES and 'Unlock Game Region' not in extra:
            extra = ';'.join(filter(None, (extra, 'Unlock Game Region')))
        # Offline, the title screen goes straight to the main menu (PLAY ONLINE would only fail
        # there); online play and co-op keep the dialog. BB_SKIP_NETWORK_CHOICE=0 shows it offline
        # too. (bbport 0.5-pre1, deadinside28 39940f2, via parsifal295's Supermedo PR #65.)
        if (env.get('BB_ONLINE') != '1' and env.get('BB_COOP') != '1'
                and env.get('BB_SKIP_NETWORK_CHOICE', '1') != '0'):
            extra = ';'.join(filter(None, (extra, 'Skip Online/Offline Choice')))
        run_script('patches.py', '--out', out, '--fps', fps, '--extra', extra,
                   '--settings', config, '--game-dir', game, '--render-res', env.get('BB_RENDER_RES', ''),
                   '--output-res', env.get('BB_OUTPUT_RES', ''),
                   '--patches-dir', env.get('BB_PATCHES_DIR', data / 'patches'),
                   '--patches-config', env.get('BB_PATCHES_CONFIG', data / 'patches.json'))
        if fps in ('120', '144'):
            # 90 FPS++ scaled to the rate (patches.py SCALED_FPS): vblank and frame limit at the
            # rate, as Awakenchan/BloodBorneButPc sets them; another cap would change its timing.
            env['BB_VBLANK_HZ'] = env.get('BB_VBLANK_HZ') or fps
            env['BB_FPS_LIMIT'] = fps
        elif not env.get('BB_VBLANK_HZ'):
            env['BB_VBLANK_HZ'] = {'uncap': '0', '90': '90'}.get(fps, '60')

        # The in-game restart starts this script again once this process is gone.
        # GPU caches (shaders, pipelines) beside the saves; read before main(), so set here.
        user_dir = Path(env.get('BB_USER_DIR', data / 'user')).resolve()
        user_dir.mkdir(parents=True, exist_ok=True)
        env.setdefault('BB_GPU_USER_DIR', str(user_dir))
        if env.get('BB_COOP') == '1':
            # Seamless co-op (BBSC) runs on the shadNet backend and the host's own servers: never
            # The Hunter's Dream's, whatever pool the main settings choose.
            for key in THD_ENV:
                env.pop(key, None)
        if env.get('BB_ONLINE') == '1' and env.get('BB_NET_BACKEND') == 'thd':
            hunters_dream(env, user_dir)
        elif env.get('BB_ONLINE') == '1':
            online_overrides(env, user_dir)
        else:
            env.pop('BB_NET_BACKEND', None)
        this = ['--run'] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())]
        restart = [sys.executable, *this, '--after', str(os.getpid()), *args]
        env['BB_RESTART_COMMAND'] = subprocess.list2cmdline(restart)
        command = [str(probe), str(out / 'boot-linked.bin'), '--content-profile', str(out / 'content.bin'),
                   '--patches', str(out / 'patches.bin'), '--app0', str(game),
                   '--user', str(user_dir),
                   '--timeout', env.get('BB_TIMEOUT', '0'), *args]
        # No stdin: an inherited pipe (shells such as Git Bash) cost the game its console output.
        game_proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, creationflags=no_console())
        started = []
        try:
            started = start_companions(data, env, game_proc.pid)
            return game_proc.wait()
        finally:
            for proc in started:
                proc.terminate()
            if game_proc.poll() is None:
                game_proc.terminate()
    finally:
        if mod_view:
            # Read-only game files leave read-only links (mods.remove_overlay clears them).
            from mods import remove_overlay
            try:
                remove_overlay(mod_view, original_game)
            except OSError:
                pass


if __name__ == '__main__':
    # The launcher reading this output may close before the game starts.
    sys.path.insert(0, str(PORT / 'scripts'))
    import quiet_output
    quiet_output.guard()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
