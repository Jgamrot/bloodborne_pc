Bloodborne (bbport) for Windows
===============================

No game files are included. You need your own decrypted dump of Bloodborne CUSA03173
(the folder with eboot.bin, sce_module, sce_sys, dvdroot_ps4). Game version 1.09 is needed for
the community patches (60/90/unlocked FPS, resolution, effects); other versions run at 30 FPS.

Requirements
- Windows 10 (1903 or later) or Windows 11, 64-bit.
- An Intel Core of the 4th generation (Haswell, 2013) or newer, or an AMD Ryzen: the game uses
  instructions of the PS4's processor (AVX, BMI1, MOVBE, LZCNT). Intel 2nd and 3rd generation
  (Sandy and Ivy Bridge) run with translated instructions, best effort. On a processor without
  AVX (many Pentium and Celeron models) the game says what is missing.
- A Vulkan 1.3 graphics card with a current driver.
- About 6 GB of free memory commit (RAM + page file), 10 GB for 1440p/4K output.
  Nothing else: Python and the libraries are inside this folder.

Starting
- Bloodborne.exe opens the first-run setup wizard on a new install. Follow its Game and
  Your data steps, or choose "Skip setup" to use the launcher directly. The wizard can
  be reopened from Game & saves -> "Setup wizard".
- On "Game & saves" choose the folder containing eboot.bin, adjust settings, then press
  PLAY. Overview shows the game version, saves, graphics card and FSR 4 assets.
- If you have cusa-03173.zip instead of an extracted game folder, use Game & saves ->
  "Install from ZIP / PKG". Choose your ZIP, then an empty destination parent folder.
  The bundled extractor applies the plain 1.09 update and sets the Game folder for you.
  With a 30 GB ZIP, allow about 70 GB of free space while it runs. Existing game folders
  are never replaced. You can also choose the base and plain 1.09 PKGs directly.
- On Game & saves, review the readiness checks before PLAY. They check the game folders and version,
  whether the trophy pack and key format are present, and whether the save folder is
  writable. Amber for saves is expected before your first save. Use "Check again" after
  copying files. Trophy-name decryption is only confirmed once the game reads the pack.
- Play Bloodborne.exe starts the game straight away with the settings saved in the launcher,
  without opening it. Set things up once in Bloodborne.exe, then use Play Bloodborne.exe (or a
  shortcut to it, or "Add to Steam" on the System page). If no game folder is chosen
  yet it opens the launcher. Bloodborne.exe --play does the same. The log goes to
  user\last_run.log.
- System -> "Desktop shortcut" puts Bloodborne on the desktop.
- Updates: when a new version is out, the launcher shows a notice; System ->
  "Install update" downloads and installs it. Saves, settings and mods are kept.
  System -> "Check for updates" checks by hand.
- The Qt Quick launcher currently displays English labels. The classic launcher retains its
  English, Russian, Arabic, Spanish, Portuguese, French, German, Italian, Polish, Turkish,
  Chinese, Japanese and Korean translations. Run Bloodborne.exe --classic-launcher to use it.
- In the game, Insert (or L3+R3 on a gamepad) opens the guide menu: Home, Achievements,
  Settings, and Mods/Cheats. Use LB/RB to switch sections, A to select, and B to go back.
  In Mods, choose PlayStation, Xbox or Keyboard key prompts, then select
  "Apply mods and restart". This also applies gameplay patch changes.
- Keyboard and mouse work alongside a controller. Default keys: WASD move, I/J/K/L camera
  (or click the window for the mouse camera), Space dodge, E interact, R blood vial, F item,
  C transform, left mouse attack, Shift + left mouse or V strong attack, right mouse firearm,
  Q lock on, arrow keys d-pad, G gestures, T personal effects, Escape menu. Rebind with
  key_<action>= lines in bbport.ini. Choosing Keyboard prompts in the launcher (it imports your
  own PCBButtons download from Nexus Mods) switches to the keys its images show instead.
- The game's System menu has a native Achievements section. Earned trophies also show an
  achievement popup and appear in the guide's Achievements section.
  In Achievements, "Preview achievement toast" tests the popup without unlocking anything.
  Unlock dates are saved in user\trophies.txt. Trophy icons come from your own game folder.
  Names, descriptions, grades and Gamerscore require your own PS4 trophy key in
  user\keys.json (see README.md). Without it, the guide shows icons and IDs. No PSN sync.

Switching from another launcher
- Keep your existing extracted game folder: this package does not include or replace game files.
- Close the old launcher and game. Back up its user folder, bbport.ini, and mods if present.
- Extract this entire package to a NEW folder. Do not copy only Bloodborne.exe into an older
  launcher folder; the matching bin, scripts, patches, and support files are also needed.
- Open this package's Bloodborne.exe. Under "Game", choose the existing folder that
  contains eboot.bin as "Game folder". Set "Saves folder" to the old user folder if you want
  those saves, or copy your backed-up saves into the new user folder while both apps are closed.
- Copy only the mods you want into the new mods folder, enable them, and press PLAY.

Data
- Saves and shader caches: user\ next to Bloodborne.exe (the launcher can pick another folder).
- Settings: bbport.ini next to Bloodborne.exe; launcher options in %APPDATA%\bbport-launcher.
- Generated files (prepared game image, patches): out\.

Online play (beta)
- Sign in to The Hunter's Dream with Discord from the Online page (approve the code on
  its website). Then choose "Online" on Overview before Play. "Test connection" checks
  server reachability; it does not verify sign-in. Seamless co-op is configured separately
  on the Online page with BBSC and Tailscale.
- Messages, bloodstains and ghosts come from The Hunter's Dream (https://thehuntersdream.com);
  bells and summons go through the shadNet server. Everyone needs game version 1.09 and the
  same co-op server. Summoning between players is not confirmed yet.

PC enhancements
- In the launcher's Mods & patches page, Hunter's Dream Mirror, Two Invaders, and Rebirth at
  the Altar are optional and off by default. They are made from your own game files at launch;
  turn one on, then restart. They do not require the Load mods switch.

Discord Rich Presence
- Optional and off by default: shows your area, boss fight, level, Blood Echoes and Insight on
  your Discord profile (Discord must be running). To turn it on, create companions.json next to
  Bloodborne.exe containing {"enabled": ["Discord Rich Presence"]}, then start the game. Its
  settings are in companions\Discord Rich Presence\config.json. It only reads the game's memory.

Cheats
- Mods & patches -> Gameplay patches has cheats (never die, enemies do not see or hear you, Rally never fades,
  control the targeted enemy) and gameplay tweaks (no Rally, camera further away, no camera
  auto-rotation, run with less stick tilt, ragdoll physics). They are game patches for 1.09,
  applied when the game starts.

Problems
- Black screen at start: System -> Maintenance -> "Clear shader cache", then start again (the first minutes
  stutter while the cache is rebuilt).
- Send user\last_run.log and the launcher log saved from Diagnostics -> "Save log..." with any bug report.
- On supported CUSA03173 1.09 images, death respawns skip the game's fixed 12-second minimum
  delay while still waiting for assets and character readiness. To restore the original delay,
  set BB_RESPAWN_DELAY_FIX=0 in System -> Engine -> Extra environment variables and restart the game.
- Water-heavy scenes use a motion-vector image for each render size instead of repeatedly
  waiting for the GPU when render-target sizes change.

Upscaling
- DLSS: NVIDIA GeForce RTX 20 series or newer with a current driver (Graphics -> Upscaler ->
  DLSS, or the in-game menu). On other GPUs the option is greyed out.
- FSR 3.1 works on every GPU. FSR 4 needs its assets in fsr4_shaders\ (included in this
  package, or Graphics -> "Download FSR 4 assets"); GPUs without the required shader features
  fall back to FSR 3.1 by themselves.

Mods and patches
- Put each mod in its own folder under mods\ (dvdroot_ps4\..., or chr\, parts\, ... directly);
  enable and order them on "Mods & patches". The game files are never changed. Without Windows
  Developer Mode the port links folders with junctions and files with hard links; when the game
  is on another drive, the temporary mod view is made next to the game folder.
- Third-party patches: shadPS4/GoldHEN XML files for 1.09 in patches\.
- Bloodborne Enhanced (Nexus mod 19) is an optional manual download from its author.
  The mod's permissions do not allow this package to include it. Place it in mods\
  and enable it in the launcher; configure its own features in game via the Doll or
  Prime Hunter's Mark.

Credits
- PKG extraction: ShadPs4Plus PKG Extractor 1.1 by AzaharPlus, GPL-2.0,
  https://github.com/AzaharPlus/shadPS4Plus. Its license is in licenses\.
- Online play: shadPS4 0.20's network code and shadNet by the shadPS4 team, put together by
  Awaken; The Hunter's Dream by droogie. The first online version was built on shadp2p by
  Wozzardman. The Hunter's Dream backend (test build) is Awaken's port of bbhost's network code (https://github.com/Awakenchan/BloodBorneButPc,
  GPL-3.0-or-later; licenses\online-code-NOTICE.md); thanks to Metr1k and The Hunter's Dream team.
- bbport (the Linux port this is built on): https://github.com/deadinside28/bloodborne_pc
- Windows port: https://github.com/Supermedo/bloodborne_pc
- The full list of projects and patch authors is in README.md (Credits and licenses).
