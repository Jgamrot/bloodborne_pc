# Changelog

Windows releases of this fork, newest first. Each is on the
[releases page](https://github.com/Jgamrot/bloodborne_pc/releases) as `bbport-windows.zip`.
Planned work is in [ROADMAP.md](ROADMAP.md).

## 2.3.1

- **The port has its own client name, `yharnam-pc`.** Online servers (shadNet, The Hunter's Dream)
  now see `yharnam-pc/<version>` instead of `bbport-jgamrot/<version>`. The Hunter's Dream stays off
  in the launcher until its team accepts this client.
- **The repository is now [Jgamrot/yharnam-pc](https://github.com/Jgamrot/yharnam-pc)** (the old
  address redirects), and releases are tagged by version (`v2.3.1`); every launcher since 1.8 still
  finds them.

## 2.3

Thirty-four community pull requests (most from xiaodoudou) and fixes for the newer issues:
the NVIDIA device losses, Ebrietas' particles, old CPUs, key bindings and Xbox pads.

**Crashes and the GPU**

- **NVIDIA "GPU device lost (WriteInvalid at 0x0)"** (#92, #130, #16, #145, #185, #212): a vertex
  shader is reused only with the same bindings (#157; pipelines are rebuilt once, so the first
  run stutters more), and a zeroed vertex input reads as zero through a valid format (#209).
  Swapchain recreation no longer races the recording threads (#160); empty images are skipped
  when tiling.
- **Ebrietas' particles** (#154, #227): effects count on whole 1/30 s steps above 30 FPS and move
  every frame (#179), so her rock effect ends; the game's GX buffer pool is 288 MiB instead of 160
  (`BB_GX_REGION_MB`, after Awakenchan 0.9.37).
- **Black blotches with SSR, white screens** (#200): shaders follow the PS4 GPU's rules for NaN and
  infinity (#204).
- **Other guards:** indirect draws with implausible counts are skipped (#173); the blur kernel's
  sample count stays at 3 or more (exit 0xa0020007, #175); render jobs give their slot back and get
  a 512 MiB cache (Laurence's cinematic, character creation, #178, #224); vertex buffer tables below
  64 KiB skip the draw (#191); stale prepared vertex inputs are read again (#192); four shadPS4
  renderer fixes (#176) and CE/DE counter waits (#177); pages the game keeps rewriting stay
  writable (#194); NVIDIA keeps its clocks up between frames (#193, `BB_NV_BOOST=0`).
- **FSR 4 on AMD** (#151): after a device loss with FSR 4, the next start uses FSR 3.1 and says why;
  choosing FSR 4 again retries it.
- **Shader cache** written by another build is rebuilt by itself (#190); pipelines without a pixel
  shader build their own fragment state (#189); the warm-up log says why stored pipelines were
  skipped (#188).

**Frame rate**

- **FPS presets below their target** play as the lower rate would: 111 per-frame constants follow
  the frame time (#201). Cloth at 60 and 90 FPS (#162) and grass and tree wind (#164) move at 30's
  pace.

**Old CPUs** (Intel 3rd generation and older, #168): the last 193 short instructions are translated
  too (#197), so nothing runs as the wrong instruction.

**Controls**

- **Key bindings page** (mdi0exe, #186): up to three bindings per action and key combinations, in
  *Settings → Controls → Key bindings*.
- **Walk on the keyboard** (#205, #88) pushes the stick 0.6 of the way, enough to walk.
- **Xbox pads** (#182): a small stick dead zone and no false centre at connect; `BB_PAD_VIBRATION_LOG=1`
  logs rumble requests (#213).
- **Overlay shortcut** (#184): *L3 + R3 opens the in-game menu* can be turned off (Insert still works);
  **Xbox View** can open Personal Effects (#228).
- **Hunter's Atlas** (#207): travel only works from the quick menu's Map; the dialog now says so.
- **Pointer after a screenshot tool** (WENlink106795, #215, #214) is no longer left hidden.
- **Button prompts without a Nexus download** (#202): choosing Xbox or Keyboard writes Kenney's
  Input Prompts (CC0) into a copy of your own `menu/common.tpf.dcx`.

**Launcher and online**

- **The Hunter's Dream is off for now** (#199): its server refuses this port's client (#10, #69,
  #152, #180, #226); a refused client stops talking to it (#198). Offline play and seamless co-op
  work as before. Online cheats, the free camera and the debug menu are off (#172).
- **Seamless co-op uses BBSC 0.0.2** (RomankinRoma, #219; #208, #217).
- **Repair** downloads this version's files when some are missing (#196, #171); Windows status
  codes reach you as hex with a hint instead of "exit code -1" (#167, #150, #153).
- **Hybrid laptops** pick the discrete GPU (mdi0exe, #187); **1366x768** output (#220, #218);
  certificates Windows trusts are trusted (#174); the in-game save no longer repeats the
  frame_gen block in bbport.ini (#203).

## 2.2

DLSS frame generation in the download, the Hunter's Atlas art back in the package, and fixes for
remappers, Proton and ultrawide monitors.

- **DLSS frame generation ships** (NVIDIA RTX 40/50): the DLSS bridge is now built from source with
  NVIDIA's frame-generation runtime, so *Frame generation → DLSS* works, with PR #134's motion
  vector and jitter fix. Packaging refuses an outdated bridge (xiaodoudou, PR #142).
- **Hunter's Atlas on a fresh install** (#143): the map art is committed and packaged again
  (xiaodoudou, PR #144); the 2.0 and 2.1 zips were missing it.
- **AutoHotkey and other remappers** (#105): arrow and navigation key bindings also accept the
  numpad key Windows reports for an injected arrow (Up as Numpad 8), unless that key has its own binding.
- **Proton / Wine** (#42): the mods overlay checks that its folder links really show the game's
  files and falls back to hard-linked folders, or starts without mods and says why, instead of
  stopping at `sce_module\libc.prx`.
- **Ultrawide and high refresh rates** (#141): with the frame rate unlocked, the cap follows the
  monitor the game opens on, not the primary one; after an in-game resolution change and restart,
  the HUD is built for the new aspect ratio.
## 2.1

Fixes ported from Supermedo's and Awakenchan's ports for open issues, four community pull
requests, and a guard for the long-session crash in #93/#83.

**From contributors**

- **Mouse flick switches lock-on targets** (LiquidRing, PR #121): a quick sideways flick while
  locked on switches targets; `mouse_flick_threshold` in bbport.ini (default 300, 0 turns it off).
- **Sign-in check and clearer start-up messages** (LDCanetti, PR #129): *Test connection* asks
  The Hunter's Dream whether it accepts the sign-in instead of trusting a saved token; a leftover
  `CUSA03173-mods` folder from BBLauncher no longer stops every start; a shadPS4 savedata folder
  chosen as the Saves folder is explained instead of starting a new save.
- **DLSS frame generation** (xiaodoudou, PR #134): motion vectors and jitter in the units DLSS
  expects; closing the window no longer freezes in the DLSS DLL's shutdown.
- **16:10 and menus** (Vaidas12345, PR #136): 1920×1200 in the launcher and the in-game menu, and
  menu/HUD composition starts at the right draw (icons along the left edge, grey loading bars).

**Fixed issues**

- **FPS falling over a long session** (#74): occlusion counts are written in order with the copy
  that clears each query, so queries finish (Awakenchan 0.9.35), and lock, semaphore and thread
  lookups no longer slow down with every loading screen (Awakenchan 0.9.34).
- **Crash at guest offset 0x2169edc after hours of play** (#93, #83): a query the game could not
  create is skipped (reported visible, as every query already is) instead of crashing; the fix
  above should stop the game running out of them in the first place.
- **"Unreachable code" GPU crash** (#140): an unknown GPU command drops the rest of its command
  buffer with a warning instead of stopping the game.
- **Game language** (#126, #133): "Unlock Game Region" is on for every text language except
  English and Russian, so Spanish, Japanese and the others show their own text (as Supermedo PR
  #91 did for Chinese), with that PR's fix that keeps online login working.
- **Windowed mode and output size** (#124, #100): the window opens at the output resolution,
  fitted to the monitor (Supermedo 5bfa7c2), and the launcher no longer writes its old values over
  what the in-game menu saved (Supermedo 40a883e).
- **Two controllers** (#113): Steam Input's virtual pad and the real one are both opened, and
  input follows the one in use (after Awakenchan 0.9.34).
- **Incomplete copy of the port** (#118): the start names the missing files and links the
  releases page instead of a Python traceback.
- **4 GB cards and full VRAM:** a low-VRAM profile, a staging pool that shrinks after load bursts,
  and a full VRAM frees unused textures and retries instead of crashing (Supermedo, ethan).
- Crash reports for crashes inside the C runtime (Supermedo 3fbe057) and for a device lost while
  presenting (Awakenchan 0.9.37).

## 2.0

Community pull requests, fixes for many reported issues, 120/144 FPS presets, and a port that
ships no game code. Everything from the unreleased 1.9.8 is included (listed further down).

**From contributors**

- **Discord Rich Presence** (erezeth, PR #77): your area, boss fight, level, Blood Echoes and
  Insight on your Discord profile. Off by default: create `companions.json` next to
  Bloodborne.exe with `{"enabled": ["Discord Rich Presence"]}` (see README-Windows.txt). It only
  reads the game's memory.
- **Trophy notifications** (GabrielTeles845, PR #115): themes (Original banner, Card, Corner
  popup), sounds, time on screen and previews in the guide under *Achievements → Trophy
  notifications*; your own sounds, GIFs, fonts and texts in `<saves>/custom_trophy`. The default
  stays the green banner with no sound.
- **Stamina cheats** (xiaodoudou, PR #101): no stamina use, always or only out of combat; they
  switch on and off without a restart.
- **Hunter's Atlas** (xiaodoudou, PR #96): the open map stays fast with fog, pickups and close
  zoom, and the Map tile follows the game's menu after submenus and Quit Game.
- **Frame generation** (xiaodoudou, PR #98): FSR 3.1 frame generation no longer leaks video
  memory (about 60 MiB a second, until the device was lost), and one long hitch no longer pauses it.
- **Striped shadows** in Chalice Dungeons on NVIDIA with an old shader cache are gone
  (xiaodoudou, PR #97).
- **Controller play hides the mouse cursor** (xiaodoudou, PR #102).
- **FSR 4 on 32:9 and 8K outputs** (MDoloresGui, PR #87, issue #81): the launcher downloads the
  4320 tier too (about 45 MB in all).
- **Co-op finds Tailscale** wherever it is installed (danyshs, PR #111).

**Fixed issues**

- Mouse camera with the "No camera auto-rotation" tweak on (#63, #108): both work together now.
- Hunter's Atlas: left click no longer jumps to the next lamp, and clicking a lamp travels to it (#41).
- Mouse in menus: hold the strong-attack modifier (Shift, or Ctrl with Keyboard prompts) and
  click for R2 / right click for L2, e.g. to switch to Storage (#64).
- *Settings → Controls → Mouse → Hide the mouse cursor in the game* for mouse-to-controller
  tools; README-Windows.txt lists every `key_*` binding and the mouse sensitivity setting (#88, #21).
- Closing the launcher while the game starts no longer stops it with "Errno 22" (#84, #91).
- The in-launcher updater delivers every new file (#38); the release zip uses forward slashes, so
  it unpacks on Linux and under Proton (#75).
- Play Bloodborne.exe starts a Bloodborne.exe set to run as administrator (#46).
- A Game of the Year PKG already at 1.09 installs without a separate update PKG (#43).
- Co-op: the firewall prompt opens in front of the launcher (#49), and account errors say what
  went wrong (server not up yet, old invite, name taken, name already signed in) (#28).
- The log names the upscaler you chose; it no longer says "FSR 3.1 (on)" while FSR 4 runs (#117).
- Mods with their own menu text (Restored Change Appearance) no longer turn the PC menu's rows
  into numbers (#48).
- A shader register that does not point at a shader skips the draw instead of crashing (#72).
- 4:3 output resolutions for CRT monitors: 1024×768 to 1920×1440 (#34).
- The game starts when another program's DLL already holds part of the PS4 address range
  (exit code 21) (#36); it reserves the free parts around it and logs the module.
- A damaged shader cache entry is skipped and compiled again instead of stopping the game at
  "loading shaders" (#80, #104).

### From 1.9.8 (never released on its own)

- **120 and 144 FPS presets**, with fixed frame steps, effect rate, cloth and follow camera
  corrected above 60 FPS; an optional frame-limiter grid (Supermedo).
- **Monitor choice and exclusive fullscreen** (Supermedo PRs #66, #68); **Circle confirms** for
  the Japanese/Asian layout (PR #17); **Brazilian Portuguese** text and voices (PR #20, issue #35).
- **Stability:** buffer arenas no longer migrate (missing objects, device lost); a faulting
  resource-table read skips that draw; a garbage PM4 header drops the rest of its buffer; a VRAM
  reserve on 4 GB cards; guest handles stay below 1 TiB (#51); 5056 MiB of direct memory when
  Windows refuses more; PC-sized graphics heaps for every player.
- **Debug menu fonts** are found in `font` or `adhoc/font` in any case; missing fonts leave the menu out.
- A plain ELF eboot.bin (no SELF wrapper) is accepted.
- **Button prompt mods are no longer in the download.** Dommo's Xbox prompts and JinkiJinn's
  PCBButtons are edits of the game's own menu file, so the port stops shipping them. Choosing
  Xbox or Keyboard in *Settings → Controls → Button prompts* opens the mod's Nexus page
  ([30](https://www.nexusmods.com/bloodborne/mods/30), [460](https://www.nexusmods.com/bloodborne/mods/460))
  and takes the file you downloaded (.zip, .7z, .rar or its `common.tpf.dcx`). Prompts already
  in your mods folder keep working. The release script now refuses to package game archives.
- **Legacy CPU plan without game bytes.** `tools/legacy-cpu-plan.json` (plan v4) and its span
  evidence keep only addresses, lengths and hashes; the original instructions are read from
  your own dump when the profile runs. The translated image is byte-identical to 1.9.7's.
- **No game code anywhere in the port.** The red-zone table (`patches/redzone.json`, 607 sites)
  and every code check in the engine (hooks for the in-game menu, mouse camera, key prompts,
  Rebirth, Hunter's Atlas, the map, aspect ratio, respawn and menu-heap fixes, The Hunter's
  Dream) now recognise the game's code by length and hash (`src/code_check.h`); hooks copy the
  instructions they displace from the running game. Tests that need original code read it from
  a prepared `eboot.elf` named by `BB_TEST_EBOOT_ELF` and skip without one.
- **Patch list without game bytes.** `patches/Bloodborne.xml` dropped 463 lines (1,073 bytes)
  that only rewrote the game's own bytes at their address. Every FPS preset, output size and
  effect/cheat setting (1,440 combinations) produces byte-identical patched memory.

## 1.9.7

A full-screen map, frame generation, seamless co-op that hands out its bells, and fixes from
the issues and from Supermedo's port. Everyone in a co-op session needs 1.9.7 for the bells.

- **Hunter's Atlas, a full-screen map** by MikeTat1988 ([HuntersAtlas](https://github.com/MikeTat1988/HuntersAtlas),
  GPL-2.0), built in: your position and facing, floors, lamps, NPCs and gates for the 16 main
  areas, with optional fast travel to discovered lamps, pickup markers and a map that opens up
  after each area's boss. *Settings → Mods & Patches → Hunter's Atlas*: turn it on and press
  *Prepare maps* once (5-15 minutes; the maps are made from your own game files). In the game,
  open the quick menu and choose *Map*. Needs the clean 1.09 game.
- **Frame generation** (from Supermedo's port): AMD FSR 3.1 on any GPU, NVIDIA DLSS on GeForce RTX
  40/50 (up to 4x on RTX 50), in *Visuals → Frame generation* and the in-game menu. 60 FPS on
  screen becomes 120; it needs a display that fast.
- **Sharper 4K:** with *Live resolution* on Auto, outputs above 1080p use the startup patch while
  depth of field is on; the live path blurred their depth of field, so 4K Native looked softer
  than 4K Performance (emurphy04, Supermedo PR #75).
- **Game of the Year dumps** whose param.sfo says 01.00 but hold the 1.09 code get the patches
  (FPS, resolution, effects) (EricDar12, PR #83); a modified eboot.bin is recognised by its code
  and left unpatched, and the launcher warns about it.
- **Crash fixes** from DarkSpartan (PR #87): lamp travel (GetBarriers assertion), random crashes
  after about an hour (the per-frame render heaps are now 1 MiB), a report instead of a frozen
  screen when the GPU device is lost, and texture hashing of unmapped memory.
- **Integrated graphics** (Ryzen laptops, ROG Ally): textures go to shared memory and the small
  dedicated heap stays free, instead of "ErrorOutOfDeviceMemory" after a while (PR #89).
- **Audio:** no more crackle or short cutouts when Windows' audio period is long (PR #80).
- **HDR on in Windows:** blacks are no longer lifted (gamma 2.2; BB_HDR_GAMMA=0 turns it off) (PR #71).
- **Offline, the title screen goes straight to the main menu** (no Play online / offline
  question) (PR #65); a damaged extraction whose shaders do not unpack is named at start instead
  of the game hanging (PR #64).
- **Chinese** (traditional and simplified) turns on the region unlock it needs, and online keeps
  working with it (PR #91).
- **More game languages** in *Settings → Game & Saves*: Portuguese (Brazil), with its dubbing,
  Portuguese (Portugal), Spanish (Latin America), English (UK), Dutch, Polish, Turkish, Finnish,
  Swedish, Danish, Norwegian, Korean and Chinese, as the game ships them
  ([#12](https://github.com/Jgamrot/bloodborne_pc/issues/12)).
- **Mods on drives without links** (exFAT, FAT32, some network drives): the game no longer stops
  with "[WinError 1] Incorrect function"; the mod overlay moves to another drive
  ([#17](https://github.com/Jgamrot/bloodborne_pc/issues/17)).
- **Discord sign-in:** the launcher also trusts the certificate roots it ships, so a PC whose
  Windows store lacks newer ones can sign in; a certificate error names the usual causes
  ([#13](https://github.com/Jgamrot/bloodborne_pc/issues/13)).
- **Opening the launcher:** a direct start waits 3 seconds with a larger, centred notice; hold
  Shift or click it for the launcher ([#11](https://github.com/Jgamrot/bloodborne_pc/issues/11)).
- **Ultrawide (21:9, 32:9), from emurphy04's work in Supermedo's port (PR #70):** wide outputs
  get the community 21:9 patch worked out for their own aspect ratio (camera, HUD, lock-on and
  health-bar markers) instead of a stretched 16:9 menu stage, which scrambled the item menu
  ([#15](https://github.com/Jgamrot/bloodborne_pc/issues/15)). Full-screen menu backdrops are
  widened, and *HUD position (ultrawide)* puts health, items and Blood Echoes at the screen edges
  or in the centred 16:9 area. The game's PC Graphics menu lists 2560 × 1080 and 3440 × 1440 and
  shows the ultrawide size you chose in the launcher (it showed 1280 × 720); 3840 × 1600 and
  3840 × 1080 are new. With the upscaler off, non-16:9 outputs draw the scene again.
- **Sharper 4K, or at least clearer:** the upscaling preset now says what size the game renders
  at (Balanced at 4K renders 2258 × 1270; Quality 2560 × 1440; Native the full 3840 × 2160).
- **Older processors** (Intel 2nd and 3rd generation, many Xeon E5 v1/v2, often paired with an
  RX 580): the game's newer instructions are translated at start, best effort, from T0ug's work
  in Supermedo's port; a CPU that cannot run the game at all is named in a message instead of
  "exit code 3" ([#14](https://github.com/Jgamrot/bloodborne_pc/issues/14)).
- **Keyboard:** a sprint is kept when you change direction (W, then A), and a half turn goes
  through forward; it used to cut across and drop to a walk.
- **Video memory full** on cards where the game's memory may live outside VRAM: it moves to
  system memory instead of stopping (from Supermedo's port). Two other upstream video-memory
  changes were tried and taken out again: on an 8 GB laptop RTX 4060 they made the game run out
  of video memory.
- **Seamless co-op gives its bells:** BBSC hands out its Hunt Bell (host) and Kin Bell (guest)
  only after it has backed up the save, and copying the save the running game had open always
  failed, so the bells never came and a new character could not start co-op. BBSC now backs up
  the copy the launcher makes before each session.
- **More from Supermedo's port:** large outputs on PCs with little RAM no longer stop at start
  (memory committed as the game maps it); a flip out of order no longer stops the game; mods on
  read-only game files load (WinError 5); more mod folder layouts load, and folders that are not
  mods are named.

## 1.9.6

Everything from 1.9.4 and 1.9.5 as a full release, plus a clearer way to choose how you play.

- **Choose how PLAY starts the game, on the Home page:** *Offline*, *Online · The Hunter's
  Dream* or *Online · Seamless co-op*. The button says which (Play offline / Play online / Play
  co-op), and a line under it says what will happen (signed in as..., hosting on..., joining your
  host...). In co-op mode PLAY starts co-op itself. When a mode still needs setting up, PLAY opens
  the right settings page.
- **Settings → Online is The Hunter's Dream only:** the Discord sign-in, UPnP and Test connection.
  The shadNet server account and address are gone; the shadPS4 team's public server refuses this
  port, and an old "Play online" with a shadNet server now starts offline.
- **The Hunter's Dream sign-in opens its website with the code filled in**, as bbhost does: sign in
  with Discord there and approve it. (Before, the code had to be typed, and the page's "code from
  the game" box is for something else.)

## 1.9.5 experimental (co-op network test)

A pre-release to test seamless co-op on the new network code; it includes everything listed under
1.9.4, which was not released on its own. Host and guests all need 1.9.5: it cannot connect to
1.9.3 or older.

- **Network code from shadPS4 0.20**, as in Supermedo's port (Awaken's adaptation): the network,
  PSN and shadNet libraries replace the shadp2p-based ones. This is what The Hunter's Dream team
  asked ports to use.
- **Co-op hosts run a fixed co-op server.** BBSC's server (Wozzardman's shadnet-p2p) ignored the
  new network code's connection-setup packets, so the bells could not bring players together.
  The port now ships that server with one fix (it answers both packet formats), built from source
  by `packaging/windows/build_coop_server.sh`. *Start hosting* uses it automatically and keeps the
  registration key, so invite codes stay valid; co-op accounts are made again on first *Play co-op*.
- **The Hunter's Dream with Discord sign-in, on the Online page:** choose The Hunter's Dream as the
  co-op pool, then *Sign in with Discord* and approve the code on its website. Test build: we are
  checking it with The Hunter's Dream team. `BB_HUNTERS_DREAM=0` hides it.

## 1.9.4 experimental (not released on its own)

Fixes from Supermedo's upstream that this fork still lacked, each checked against our own code first,
and The Hunter's Dream online backend, still hidden.

- **No more stop when the graphics driver refuses a pipeline** ("Failed to create graphics pipeline:
  ErrorUnknown", code 23, mostly AMD): its draws are skipped and it isn't cached. Motion-vector
  pipelines are no longer preloaded from the cache, the root cause of most of those refusals.
- **Crash fixes:** the texture cache's image list no longer moves in memory while an image is in use
  (a crash in FindDepthTarget); the GPU command recorder always has a chunk to write into; a garbage
  GPU command header drops the rest of that buffer instead of stopping the game.
- **AMD RX 6000 (RDNA2):** object motion no longer loses the device; it is off on AMD cards before
  RDNA3 (`BB_OBJECT_MOTION=1` to test it).
- **Physics at 60, 90 and uncapped frame rates:** the FPS presets now set the physics step to the
  right value, not the patch file's 1/15 or 1/30 of a second (ragdolls, cloth, falling).
- **Video memory full:** an allocation the driver's budget refuses is made past it instead of
  stopping the game; old render targets of areas left behind can be freed.
- **Fewer texture-upload checks:** only images the GPU may write keep a hash of their upload.
- **Shader resource walker:** reads made ahead of the game fall back to their recovery point instead
  of permanently changing the walker.
- **Display:** no title-menu flicker above 1080p (parsifal295, #56); the loading screen's item
  picture stays at outputs other than 1080p (bmy via parsifal295, #62).
- The GPU, its video memory and the driver are named at the top of every log.
- **The Hunter's Dream:** Supermedo's port of Awaken's backend
  (bbhost's protocol, GPL-3): Discord sign-in by code on the Online page, the game's server
  functions over HTTP to the game server only. Not offered until its team has agreed. This build
  reports itself as `bbport-jgamrot <version>`. Seamless co-op keeps its own network code and
  never uses this backend.

## 1.9.3 experimental

- **Co-op bells: BBSC now gives its Hunt Bell and Kin Bell.** BBSC replaces the vanilla bells with
  its own co-op kit, but only after backing up the save, and it couldn't find this port's saves
  ("BBSC kit: no save folder found to back up"), so nobody got the kit and the guest couldn't
  ring a bell. Co-op launches now tell BBSC where the save is.

## 1.9.2 experimental

A pre-release: the launcher does not offer it as an update. Fixes for seamless co-op, found in
the first test of 1.9.1:

- **The game no longer exits (code 3) when it starts with seamless co-op.** While the game
  loaded, every page of its memory was briefly made unreadable before each part got its own
  protection. BBSC checks some of that memory from another thread every few milliseconds, and
  a check in that moment ended the game (`Fault: read access ... at bbsc.dll+0x1933`). Only
  memory the game doesn't use is made unreadable now. For co-op, the game code also stays
  writable, as BBSC expects from shadPS4.
- **BBSC finds the host's server.** It looks for the host's address in its own places, and
  1.9.1 put it somewhere else, so warps and world sync had no server ("Relay: no game server
  address"). Co-op launches now give BBSC the address directly.
- **Stop hosting stops the whole server.** BBSC's game server runs a second copy of itself, which
  kept running after Stop hosting or closing the launcher and kept the co-op ports busy. Both
  copies stop now, and Start hosting first ends any that were left over.

## 1.9.1 experimental

A pre-release: the launcher does not offer it as an update. It is 1.8.3 (with everything in
1.8.2) plus the seamless co-op of 1.9 and boss rematches for every boss with a lamp.

- **Seamless co-op is how to play together for now.** The public shadPS4 server
  (srv.shadps4.net) signs this port out since its 14 October update, whatever version the port
  reports (1.8.3's `shadPS4 Jgamrot/v0.20.0` too); shadNet's stock rules would accept it, so this
  is that server's own setting. Co-op doesn't use it: one player hosts the servers on their own
  PC. The Online page now says this.
- **Seamless co-op (experimental):** Settings > Co-op sets up and runs
  [BBSC](https://github.com/Classmg22/BBSC) (Bloodborne Seamless Co-op by CLS_AMG; servers from
  Wozzardman's shadnet-p2p): one co-op session through deaths, lamps, areas and bosses, each hunter
  keeping their own character. One player hosts the server on their own PC; both use
  [Tailscale](https://tailscale.com). *Set up co-op* downloads BBSC's official packages and checks
  them against its published checksums; *Start hosting* opens the firewall for Tailscale and the
  home network only (one Windows prompt, the first time), starts the servers and gives an invite
  code; the guest pastes it; *Play co-op* backs up the saves and starts the game with BBSC, pointed
  at the host for that session only. The game runs on this release's engine, so 1.8.2's video
  memory and menu fixes apply in co-op too. Not yet played through on BBport: please report
  problems with `user\last_run.log` and BBSC's logs.
- **Boss rematches (experimental, off):** *PC gameplay enhancements* has a toggle for rematches
  at the bosses' own lamps: once a boss is defeated, the lamp its defeat lit offers "Rematch ..."
  next to Level Up and Storage, for one Insight when you have any. All 19 bosses with a lamp of
  their own: Cleric Beast, Father Gascoigne, Blood-starved Beast, Vicar Amelia, the Witch of
  Hemwick, Darkbeast Paarl, Shadow of Yharnam, Rom, the One Reborn, Martyr Logarius, Amygdala,
  Celestial Emissary, Ebrietas, Mergo's Wet Nurse, Ludwig, Living Failures, Lady Maria, Laurence
  and Orphan of Kos (not Gehrman, the Moon Presence or Micolash, who have no lamp). The fight is
  staged as the first meeting; winning, dying or leaving puts the arena back. The save's
  defeated-boss flags are never cleared and a rematch kill gives no first-kill items, trophy or
  progression again. Played through on the Cleric Beast; the other 18 are made the same way and
  checked against the game's scripts, but not yet played: back up your saves first. Boss data
  after droogie's bbhost (boss rush plugin).
- **Fixed with it:** with rematches on, Central Yharnam's other lamps lost Level Up and Storage;
  with the two invaders on as well, the rematch layer undid their change in five late maps.

## 1.8.3

- **Version report changed; online still refused.** Since 14 October the shadNet server checks
  the version a client reports and signed 1.8.2 out ("This shadNet server doesn't accept your
  shadPS4 build"). 1.8.3 reports itself the way shadPS4's own fork releases do,
  `shadPS4 Jgamrot/v0.20.0`, and keeps the port's version in the log. The public server refuses
  that too (see 1.9.1).

## 1.8.2

- **Video memory no longer runs out on 4 GB cards** ([#3](https://github.com/Jgamrot/bloodborne_pc/issues/3)).
  Memory given to the game's buffers was never released, so usage grew with every area until
  `ErrorOutOfDeviceMemory` after an hour or two. When video memory gets short, buffers unused
  for a few seconds now give theirs back; cards with room to spare behave as before.
  `BB_BUFFER_GC=0` turns it off. *Settings → Graphics → Video memory* can start clearing
  earlier (a pressure target, not a hard cap; Automatic by default).
- **Opening PC Graphics, PC Display and the other PC sections no longer crashes with button
  prompt mods** ([#3](https://github.com/Jgamrot/bloodborne_pc/issues/3)). The menus' fixed
  Scaleform memory is mostly taken by `menu/common.tpf`; the Xbox 360 Prompts mod's larger copy
  left too little for a PC section (a crash at `0xdcf79`). The menus get 8 MB more
  (`BB_MENU_HEAP_EXTRA_MB=0` keeps the original size).
- **A damaged `.dcx` file no longer stops the game** ([#8](https://github.com/Jgamrot/bloodborne_pc/issues/8)):
  the feature that needs it turns off with a log line, and a failing PC enhancements or shader
  pre-build step lets the game start as with that step off.
- **Installer: a renamed plain 1.09 update PKG is accepted** (a browser's `(1)`, store-style
  names). Only names that look like the 60 FPS variants are refused, each step says whether it
  wants the base game or the update, and picking the same PKG twice is refused.
- **Touchpad gestures:** each touch now gets its own ID and a hold time, as a DualShock 4
  reports them, instead of zero for every sample.
- **Missing walls and floors you could walk through** ([#6](https://github.com/Jgamrot/bloodborne_pc/issues/6)).
  Now and then a piece of a map loaded without its model or collision, and it stayed broken
  until the game was closed. The game reads its archives two ways at once: one thread moves to a
  position and reads, another reads at a given position. On Windows the second kind moved the
  file's position and put it back, so a read from the first thread could land in the wrong place
  and load garbage. Those reads now take turns on each open file (Windows already ran them one
  at a time). A stress test that failed every run before now passes; confirming it in play
  needs time, since the bug was rare.

## 1.8.1

- **Online works again.** Since 12 October the shadNet server signs out clients that do not
  report their version straight after signing in, then refuses their logins for two minutes:
  every login of the port failed and the game showed it could not connect. The game now reports
  itself (`shadPS4 Jgamrot/bloodborne_pc v1.8.1`), as shadPS4 does; if a server ever turns it
  away, the log shows the server's message.
- **Trophy names after choosing a saves folder.** The setup wizard offers *Import trophy keys*
  before *Choose a saves folder*; the key stayed in the old folder and trophy names were missing.
  Choosing a saves folder now copies `keys.json` over when the new folder has none.

## 1.8

A full release: the launcher offers it as an update. It is 1.7 plus the following.

- **Shader pre-build.** Shaders the game has been seen to use are built while the game starts
  ("Preparing shaders: N%" in the window title), not the first time an area or effect appears.
  The shipped catalog (`shader_catalog/`) lists which shaders and pipelines the game uses, never
  game code: each install builds them from its own game files, for its own GPU and driver, and
  keeps them, so later starts take a second or two. Every catalog entry was checked to build
  byte for byte like the game's own. This first catalog covers the game up to the
  Blood-starved Beast; later releases extend it. On a fresh install loading into Central
  Yharnam it cut the shaders compiled during play from 479 to 2 and the worst frame from 639 to
  181 ms (RTX 4060 Laptop). On AMD and Intel GPUs most fragment shaders do not match yet and
  still compile in play as before. Off with `BB_SHADER_PREBUILD=0`.
- **Keyboard movement smoothing.** Holding W and then pressing A or D no longer stops the
  character for a moment: the stick swings to the new direction over a few frames
  ([#4](https://github.com/Jgamrot/bloodborne_pc/issues/4), after MKB2Controller's setting,
  suggested by tmntanno). Settings > Controls > Keyboard, *Off* to switch it off
  (`move_smoothing=100`).
- **GPU readbacks: Precise no longer stays on a black screen at start**
  ([#2](https://github.com/Jgamrot/bloodborne_pc/issues/2), reported by HerOisPerO). Precise
  waits for the GPU whenever the game reads memory the GPU wrote; the port's draw recording and
  copy threads deadlocked against it. They are off under Precise, so it costs some speed; it
  should catch the stale face vertices (FaceGen, the "vertex explosions") that Relaxed can miss.
- **No crash out of bounds.** A texture descriptor with an impossible format (seen after
  falling out of the map) no longer stops the game.
- **Video memory:** the texture cache starts evicting at 80% of a discrete GPU's budget, not
  40%, which removed constant evictions and uneven frame times in Yharnam on 8 GB cards.
- **The last three game logs are kept** (`last_run.log`, `last_run.1.log`, `last_run.2.log`),
  so starting again after a crash keeps the log of the run that crashed.

## 1.7

A full release: the launcher offers it as an update. It includes everything in the 1.6.12 and
1.6.13 previews below. Shader pre-building and the shadPS4 catch-up come in 1.8; boss
rematches stay a hidden experiment (`BB_PC_REMATCHES=1`) until tested.

- **Redesigned launcher.** One minimal layout: an icon rail (Home, Settings), a Home page
  with a single status line and one primary button (Play, or the fix that blocks it), and four
  rows for Graphics, Controls, Game files and Mods. Settings is a category list with search on
  the left and sectioned rows on the right. The setup wizard uses the same style. Builds on
  Codex's redesign branch; colours and type come from one theme file (`launcher/qml/Theme.qml`).
- **Redesigned in-game guide**, in the launcher's style: an icon rail, a Hunt page of menu
  rows, and settings laid out as label/control rows with switches. Every option is where it
  was and does the same thing.
- **Keyboard prompts included.** JinkiJinn's [PCBButtons](https://www.nexusmods.com/bloodborne/mods/460)
  key images ship with the port (its permissions allow it, with credit), so choosing Keyboard no
  longer asks for a download. They arrive switched off beside the Xbox prompts; the launcher and
  the guide can both choose them.
- **Guide controls.** Console-style movement: along the icon rail the page follows, Right enters
  the page and Left returns to the rail. L3 + R3 is shown as the way to close; on a keyboard,
  Insert opens and closes the guide. The mouse pointer shows as soon as the guide opens.
- **Mouse pointer in the game's menus.** Point at a row to move the game's cursor there, click
  to choose it (on an option's value, the side you click steps it), right-click to go back, and
  scroll with the wheel. It works in the title, System, the PC sections and the other menus
  with lists. While a menu is open the window shows the pointer; the mouse camera takes the
  mouse back when the menu closes. Mouse buttons do not trigger their gameplay bindings in
  menus. Off with *Mouse pointer in the game's menus* in Settings > Controls > Mouse (`mouse_menu=0`,
  `BB_MOUSE_MENU=0`). Ported from [droogie's bbhost](https://github.com/droogie/bbhost)
  (`menu_pointer.cpp`, GPL-3.0-or-later).
- **The game no longer stops at start when DLSS cannot load** although the NVIDIA driver
  advertised it: device creation is retried without DLSS and FSR 3.1 is used; your DLSS choice
  is kept for the next start ([deadinside28 #140](https://github.com/deadinside28/bloodborne_pc/pull/140),
  Obrikash).
- **A lost GPU device on a particle effect** whose indirect dispatch read garbage group
  counts: implausible counts are now skipped and reported
  ([Supermedo #41](https://github.com/Supermedo/bloodborne_pc/pull/41), parsifal295, from
  bbport 0.5). `BB_INDIRECT_GUARD=0` restores the old behaviour.
- **Clone pads that spin the camera or never run:** each pad's stick neutral is measured when
  it connects, and an axis that only uses part of the range is scaled to full deflection, so
  knock-off controllers (for example Switch Pro clones) read correctly. A genuine pad reads as
  before. `BB_PAD_CENTER_CAL=0` turns it off; `BB_PAD_DEADZONE` sets an inner dead zone
  ([deadinside28 #71](https://github.com/deadinside28/bloodborne_pc/pull/71), Bainianzzz).
- **Every retail release recognised:** external patch files, mods wrapped in a serial folder
  and the save sound fix now accept all nine retail Bloodborne serials (Japanese and US Old
  Hunters editions included), which run the same 1.09 game
  ([Supermedo #47](https://github.com/Supermedo/bloodborne_pc/pull/47), parsifal295, from
  bbport 0.51).
- **Safer saves:** a save file is written to a copy and replaces the old one in a single step,
  so a crash or a kill while the game saves can no longer leave a damaged save
  ([Supermedo #43](https://github.com/Supermedo/bloodborne_pc/pull/43), parsifal295, from
  bbport 0.5). `BB_SAFE_SAVES=0` writes in place as before.
- **Key items on Xbox pads:** Back + d-pad right clicks the right half of the touchpad (key
  items, and the right-hand choice of some prompts), Back + d-pad left the left half; Back on
  its own still opens gestures, now when released
  ([Supermedo #39](https://github.com/Supermedo/bloodborne_pc/pull/39), parsifal295).
  `BB_PAD_BACK_COMBO=0` restores the old Back.
- **Less GPU work for nothing:** draws with no colour or depth target and no memory writes,
  which on the PS4 only fed occlusion counters this port answers itself, are skipped
  ([Supermedo #34](https://github.com/Supermedo/bloodborne_pc/pull/34), Aljoscha-Ide).
  `BB_SKIP_EMPTY_DRAWS=0` draws them.
- **Smoother frame times on 8 GB GPUs:** the texture cache starts evicting at 80% of a
  discrete GPU's memory budget instead of 40%, so textures in use are no longer dropped and
  uploaded again in Yharnam (issue #32).
- **The log of a crashed run is kept:** the launcher keeps the last three game logs
  (`last_run.log`, `last_run.1.log`, `last_run.2.log`) instead of overwriting one.
- Developers: `overlay-preview` (an opt-in build target) renders the guide to an image
  without starting the game.

## 1.6.13 preview

A pre-release, like 1.6.12: the launcher's updater does not offer it until a full release
follows. It includes everything in 1.6.12.

- **Frame cap holds for every frame**, not only on average: no single frame comes faster than
  the cap any more, which made running slow down for a moment at 120 FPS
  ([#28](https://github.com/Supermedo/bloodborne_pc/pull/28), DUDUYG). `BB_STRICT_FRAME_CAP=0`
  restores the old limiter.
- **Sprinting no longer sticks at half speed above 90-120 FPS** after bumping into something:
  the game's blocked-movement check assumed 30 FPS and now uses the real frame time. Applied
  with every preset above 30 FPS, only when the game's code is exactly as expected
  ([#33](https://github.com/Supermedo/bloodborne_pc/pull/33), Aljoscha-Ide; the same fix as
  [#31](https://github.com/Supermedo/bloodborne_pc/pull/31), DUDUYG). `sprint_fix=0` in
  bbport.ini or `BB_SPRINT_FIX=0` turns it off. The 120 FPS cap stays the default.
- **A crash while a map loads** when a shader's descriptor table is unbound: the read now
  returns an empty descriptor, which the renderer already handles, instead of reading address
  zero (parsifal295's fix from [Mrsuss60's Windows port](https://github.com/Mrsuss60/bloodborne_pc_windows_port)).
- **Mods when started from Armoury Crate** (ROG Ally) and other launchers that start games with
  Windows' redirection trust policy: the game no longer stops with "the path cannot be traversed
  because it contains an untrusted mount point". When folder links are refused, the mod overlay
  uses real folders of hard-linked files instead (a few seconds longer at start, only then).
  Reported by Sjknight413 on r/BloodbornePC.
- **Update check on direct launches.** Starting the game straight from a shortcut or Steam now
  asks GitHub quietly, 20 seconds after the game starts and at most every 6 hours, and only
  remembers the answer. The next time the launcher opens, the Home banner shows the new version
  at once, with **Install update** beside **View release**. Off with the launcher's *Check for
  updates* switch, like every other check.
- **Graphics presets** on the Graphics page and in the setup wizard: Low, Balanced, High and
  Ultra, with a ★ on the one suggested for the detected graphics card (by video memory). They
  change only settings that cost GPU time (upscaling factor, model detail, SSAO, dynamic-light
  shadows, screen-space reflections, frame rate); the upscaler, output resolution and look-only
  effects stay as you set them. Balanced is the shipped defaults, and any change of your own
  shows as Custom. Each graphics setting now says what it does. After Lantern Launcher's idea
  (par274), not its values.
- **Ultrawide, 16:10 and other aspect ratios**: new output resolutions (2560x1080, 3440x1440,
  5120x2160, 5120x1440, 1280x800, portrait) and any WxH typed in the classic launcher. The
  camera is widened with the vertical field of view kept, the HUD stays centered at 16:9, and
  enemy health bars reach the wider edges. Only on the verified 1.09 game; aspect changes need
  a restart. `BB_ASPECT=0` turns it off. From
  [Supermedo #12](https://github.com/Supermedo/bloodborne_pc/pull/12) by FIocker, adapting
  [bbhost](https://github.com/droogie/bbhost)'s camera and UI fixes (GPL-3.0-or-later).

## 1.6.12 preview

A pre-release: the launcher's updater does not offer it until a full release follows.

- **Keyboard button prompts.** Choose Keyboard on the launcher's Controller page, or Keyboard
  keys in the Insert/L3+R3 overlay's Mods tab, beside PlayStation and Xbox; either place can
  switch back. The first time, the launcher imports the key images from your own download of
  [PCBButtons](https://www.nexusmods.com/bloodborne/mods/460) (not included) and binds the keys
  they show. If you rebind keys, menu and tutorial text names your keys instead (after bbhost's
  key prompts; started by Codex).
- **Lamps: Level Up and Storage** (`pc_enhanced_lamps`, off by default). Every lit lamp also
  offers the game's own Level Up and Storage screens once the Doll and the storage box have
  been used. Works alongside Rebirth, which edits the same Nightmare archive.
- **Fixes from Supermedo pull requests**, with their authors' commits:
  - the black character preview in character creation: the texture cache no longer copies
    stale game memory over images the GPU drew
    ([#36](https://github.com/Supermedo/bloodborne_pc/pull/36), yumlevi's fix);
  - a crash while an area loads, in shader walkers loaded from the pipeline cache
    ([#29](https://github.com/Supermedo/bloodborne_pc/pull/29), DUDUYG);
  - video memory growing with every area visited: images that cannot be freed no longer block
    the collector, and idle textures go after 20 s (`BB_GC_IDLE_SECONDS`)
    ([#32](https://github.com/Supermedo/bloodborne_pc/pull/32), parsifal295, from bbport 0.3).
- **Boss rematches, experimental:** a Cleric Beast rematch at its lamp for testing in play
  (`BB_PC_REMATCHES=1` in the launcher's Advanced overrides; no toggle yet). The permanent
  defeat flag and first-kill rewards are left alone. Not offered to players until tested.
- A tidier README, this changelog and a roadmap.

## 1.6.11

- Achievements is back in the game's own System menu; the six custom sections are
  Achievements, PC Graphics, PC Display, PC Effects, PC Settings and PC Gameplay.
- PC Enhancements (Hunter's Dream mirror, two invaders, Rebirth) moved to the launcher's Mods
  page.
- The Online page links to shadNet registration.

## 1.6.10

- Mouse camera: click the game window and the mouse turns the camera 1:1 (imedved's camera,
  ported by mcrib884 and Jhony-Jhansen). Settings on the Controller page.
- DLC folder for base-game dumps ([ayozetr, #26](https://github.com/Supermedo/bloodborne_pc/pull/26)).
- Upstream fixes, with their authors' commits: the Intel 12th-gen attack crash (DarkSpartan),
  texture eviction under video-memory pressure (gtggdd4mzb-source, yumlevi), a GPU command
  race (andrecabralgit), UTF-8 configuration (noatdk), the 1.09 FPS physics address
  (FIocker), quiet stereo audio (andrecabralgit), shadNet summons (jpramosjp) and mods on
  Windows with Developer Mode (gStone).

## 1.6.9

- The L3+R3 overlay's settings in the game's own Options menu, with fullscreen while playing
  and Restart to Apply; menu engine ported from [bbhost](https://github.com/droogie/bbhost).
- Achievements as a System row on the title screen and in game.
- Rebirth in the Nightmare at the Altar of Despair (`pc_rebirth`, off by default).
- Keyboard and mouse alongside the gamepad, with rebindable keys (`key_<action>=` in
  `bbport.ini`) and mouse-wheel actions.

## 1.6.8

- Display buffers are released before the game hears a flip has completed, fixing the
  intermittent "Out of order flip IRQ" assertion.

## 1.6.7 and earlier

- Qt Quick launcher with a first-run setup wizard, direct launch (`Play Bloodborne.exe`), an
  installer for your own ZIP or PKG dump, and an update check.
- Xbox button prompts by Dommo bundled in every package.
- Insert/L3+R3 guide with Home, Achievements, Settings and Mods tabs, local trophy history and
  achievement toasts (names and scores need your own trophy key in `user\keys.json`).
- Optional Hunter's Dream mirror and two invaders (`pc_mirror_appearance`, `pc_two_invaders`).
- English in-game settings menu ([#13](https://github.com/Supermedo/bloodborne_pc/pull/13)) and
  working checkboxes and sliders ([#19](https://github.com/Supermedo/bloodborne_pc/pull/19)).
- Death respawns skip the fixed 12-second wait (after
  [AwesomeObserver](https://github.com/AwesomeObserver/bloodborne_pc/blob/windows/docs/respawn-loading-windows.md));
  `BB_RESPAWN_DELAY_FIX=0` restores it.
- Shader preload reuses loaded modules; motion vectors keep images for several render sizes,
  addressing the [water-area slowdown](https://github.com/deadinside28/bloodborne_pc/issues/30).
