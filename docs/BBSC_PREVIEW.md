# BBSC seamless co-op preview

This is an optional launcher for [Classmg22's BBSC 0.0.1 BBport test package](https://github.com/Classmg22/BBSC/releases/tag/v0.0.1). BBSC and its binaries are downloaded separately; they are not part of this repository or the normal BBport build.

BBSC's own `HOW-TO-PLAY.txt` says that its DLL loads in native BBport but that **co-op on native BBport has not yet been tested**. This launcher integration has been checked against BBport's `BB_PROBE` launch hook and tested for backup and configuration restoration. It has **not** been played with two clients. Do not describe it as working co-op until a two-client run confirms joining, travel, death, boss completion, progression, and a normal online launch afterward.

## Try the preview

1. Use a packaged Windows build of this fork with a working CUSA03173 version 01.09 game folder and the default `user` saves folder. The test package asks for its own account; the normal shadNet account is separate.
2. Download `BBSC-0.0.1-BBport.zip` from [BBSC's release](https://github.com/Classmg22/BBSC/releases/tag/v0.0.1) and extract it outside the BBport folder. Its published SHA-256 is `2a0fecfea5178ee685616b933989620a4eb14892048ce85af6da350334f86649`.
3. Open **Online → Launch BBSC preview** and select the extracted `BBSC-0.0.1-BBport` folder. The classic launcher offers the same entry.
4. Finish BBSC's account prompt, then choose online at Bloodborne's title screen. The host uses the Hunt Bell; guests use the Kin Bell. All players need matching game files and the same BBSC mode/server.

The preview copies `user/savedata` to `user/bbsc-preview-backups/<timestamp>/savedata` before launch. It temporarily supplies BBSC with this build's `Bloodborne.exe` and game folder. When BBSC's wrapper exits, it restores the exact previous `user/host_overrides.custom.json` and the package's previous `tools/bbport-paths.json` (or removes those files if they did not exist). Keep the launcher process running until the BBSC session has ended so it can report the result. BBSC's account data stays in its extracted package.

BBSC 0.0.1 reports that Chalice Dungeon co-op is unsupported and a full party wipe can respawn the host in the Hunter's Dream. Send gameplay bugs with both the BBSC log and `user/bbsc-run.log` from the BBport folder to [BBSC's issue/community channels](https://github.com/Classmg22/BBSC).

## Technical boundary

The BBSC package sets `BB_PROBE` to its `bbsc-launch.exe`, which starts this fork's `bin/bb-probe.exe` with BBSC's DLL. It uses the existing `run.py` path, so the standard renderer and port files remain in place. It also writes `user/host_overrides.custom.json` to reach its own server; the preview restores this file because `run.py` would otherwise continue using it for later normal online launches.

This is a sidecar experiment. A native integrated co-op release would require source-level compatibility work and two-client gameplay testing. See also [Wozzardman's shadp2p fork](https://github.com/Wozzardman/shadp2p), [deadinside28's draft bbport co-op PR](https://github.com/deadinside28/bloodborne_pc/pull/130), and [visy's native Windows party co-op fork](https://github.com/visy/bloodborne_pc_windows_port).
