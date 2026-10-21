# Windows launcher

The Windows launcher is a PySide6/Qt Quick desktop application in `windows_laucnher/`
(the misspelling is intentional). It configures the game, prepares its files, starts and
stops the game process, and exposes diagnostics. The classic Tk fallback remains available
when Qt Quick cannot start.

The launcher UI was reworked around a single persistent navigation rail. The Windows
backend, settings keys, executable, packaging toolchain, and Windows process model are
unchanged.

![Overview](images/launcher-overview.jpg)

## Status labels used in this document

- **Implemented** — present in the source tree.
- **Unit-tested** — covered by a test that runs without a window.
- **Build-verified** — a real Windows PE launcher was produced.
- **Launcher-runtime-verified** — the launcher itself ran and was exercised under the
  stated environment.
- **Wine-verified** — the launcher ran under Wine.
- **Proton-verified** — the launcher ran under Steam Proton.
- **Game-launch-verified** — the game process reached its own running code.
- **Gameplay-verified** — a playable session was exercised.
- **Blocked / Failed / Not verified** — no claim is made.

## Pages

| Page | Contents |
|---|---|
| **Overview** | Launch state, offline/online/co-op mode, primary Play/Stop action, readiness checks, current graphics summary, quick links, update notice. |
| **Graphics** | Graphics presets, upscaler and preset, live resolution, sharpening, object-motion vectors, frame generation, image effects, video-memory behavior, overlay. FSR 4 asset download and status. |
| **Display** | Output resolution, HUD position, fullscreen, HDR, frame-rate mode, unlocked-mode limit, frames ahead, presentation mode. |
| **Game & saves** | Game folder, DLC folder, saves folder, trophy keys, language, hunter name, skip-intro, button prompts, mouse, keyboard. Install-from-archive and readiness actions. |
| **Mods & patches** | Installed mods and load order, built-in enhancements, Hunter's Atlas, external patches, gameplay patches. |
| **Online** | The Hunter's Dream sign-in and connection test, plus seamless co-op setup, hosting and invite flow. |
| **System** | Launcher language, direct-start behavior, desktop/Steam shortcuts, updates, draw pipeline/readbacks/extra environment, developer diagnostics, maintenance. |
| **Diagnostics** | Process state, last exit code, log line/error/warning counts, runtime report, paths, copy/save/clear log, shader-cache clear, live log with severity colouring and follow mode. |
| **Setup** | Four-step first-run wizard: welcome, game files, saves/trophies, graphics/finish. |

Every existing field and action from the old category workspace has a home. The mapping is
declared in `launcher/bbport_launcher_backend.py` (`LAUNCHER_PAGES`), and
`tests/test_launcher_pages.py` asserts that every settings section and field is reachable
(excluding the dedicated Diagnostics page).

![Graphics](images/launcher-graphics.jpg)

## Architecture

- `launcher/qml/Main.qml` — application shell, persistent navigation, top status bar,
  search field, compact Play/Stop action, page container, and persistent footer status.
- `launcher/qml/Rail.qml` — named navigation rail and the live launcher/game state.
- `launcher/qml/HomePage.qml` — Overview.
- `launcher/qml/SettingsWorkspace.qml` — renders the section groups returned by
  `launcher.pageSections(pageKey)` in reading order, plus the search results view.
- `launcher/qml/SectionActions.qml` — the actions that belong to a section (install,
  sign-in, co-op, mods, maintenance, and so on).
- `launcher/qml/DiagnosticsPage.qml` — live process/runtime/path/log view.
- `launcher/qml/SetupWizard.qml`, `Splash.qml` — first-run setup and the direct-launch
  splash.
- `launcher/qml/Glass*.qml`, `FieldRow.qml`, `MenuRow.qml`, `ToggleRow.qml`, `Note.qml`,
  `NavIcon.qml`, `Theme.qml` — shared controls and design tokens. The historical filenames
  are retained to keep the change focused; the controls are flat surfaces, not glass.

Process ownership stays in `bbport_launcher_backend.py`. Page visibility and window state
never decide whether an operation completes. The backend exposes:

- `launchState` (`ready`, `starting`, `running`, `preparing`, `failed`)
- `lastExitCode`
- `runtimeInfo` (`gpu`, `upscaler`, `objectMotion`, `presentMode`, `output`, `error`)
- `logStats`, `logLines`, and `paths`
- `pageSections(page)` / `pageFor(category, section)` (with pure helpers used by tests)
- `action("openLogs")` and `action("exportLog")` alongside the existing copy/clear actions

Settings still go through the existing validated, atomic-write path. Unknown settings keys
are preserved, malformed files fall back safely, and the QML controls do not write directly
to disk.

Page changes are plain `visible` bindings in `Main.qml`. There are no page-transition
animations, repaint timers, sleeps, page recreation loops, or fullscreen toggles.

## Wine page-transition fix

The Wine-specific rendering fix is unchanged and is required for the new shell:

- `launcher/bbport_launcher_win.py` detects Wine/Proton and sets
  `QSG_RHI_BACKEND=opengl` only when the user has not chosen a backend.
- `launcher/bbport_launcher_qml.py` applies the same configuration before importing
  PySide6.
- Native Windows keeps Qt's default Direct3D 11 backend.

Root cause and regression procedure: [WINE_LAUNCHER_RENDERING.md](WINE_LAUNCHER_RENDERING.md).

## Build

### Full package

Follow [packaging/windows/README.md](../packaging/windows/README.md). From an MSYS2
**CLANG64** shell:

```bash
bash build.sh
bash packaging/windows/package.sh
```

`package.sh` freezes the launcher with PyInstaller, collects `bb-probe.exe` and its
CLANG64 DLLs, and assembles `dist/bbport-windows/`. This machine has no MSYS2 CLANG64
sysroot, so the native runtime could not be rebuilt here.

### Launcher-only build used for this task

A genuine Windows launcher was frozen under Wine with Windows Python 3.12.10,
PyInstaller 6.22.3, and PySide6 6.12.0:

```bash
WINEPREFIX=... wine 'C:\bbport-python\python.exe' -m PyInstaller \
  --noconfirm --clean --windowed --name Bloodborne \
  --icon launcher/assets/hunter-icon.ico \
  --distpath out/wine/pyi-dist --workpath out/wine/pyi-work \
  --paths scripts --paths launcher \
  launcher/bbport_launcher_win.py
```

The package was assembled under `out/wine/package/bbport-windows/` with the frozen
`Bloodborne.exe`, `_internal/`, QML files, assets, `run.py`, and scripts. The executable is
a real Windows PE32+ GUI binary:

```text
PE32+ executable for MS Windows 6.00 (GUI), x86-64
SHA-256 4dbd863e40545f26bc5b8c3a1fb37f1b308e679c3eaaa0a3b78af40772a472b6
```

The launcher-only package intentionally has an empty `bin/`; it cannot start the game
without a native `bb-probe.exe`. Build artifacts under `out/` are not committed.

## Tests

```bash
python -m unittest discover -s tests
python -m unittest tests.test_launcher_pages -v
```

Observed on this machine:

- 321 tests: **2 errors, 77 skipped**. The pre-rework baseline was 315 tests with the same two errors and 77 skips; the six new page-mapping tests pass.
- Windows launcher settings tests: **21 passed**.
- Renderer selection tests: **4 passed**.

The two known baseline errors are unrelated to this work:

- `test_hunters_dream...test_https_trusts_the_shipped_roots_and_explains_certificate_errors`
  reads the certifi bundle with the host's ASCII default encoding.
- `test_mods...test_overlay_moves_off_a_drive_without_links` resolves a simulated Windows
  path through POSIX `realpath` on this Linux host.

## Wine verification

Environment used for the packaged launcher check:

- Wine 11.18 (Staging), 64-bit prefix.
- Windows Python 3.12.10, PySide6 6.12.0, PyInstaller 6.22.3.
- Xvfb `:99`, 1600x1000, **no window manager**, OpenGL Qt Quick RHI.
- Package: `out/wine/package/bbport-windows/Bloodborne.exe --launcher`.

Observed:

- The packaged window appeared at 1360x860 and rendered frames 1–2.
- Navigation to Graphics, Display, Game & saves, Mods & patches, Online, System,
  Diagnostics, and back to Overview produced the new page and a following present frame
  each time (for example `QML page=Graphics` followed by `frame 3 page='Graphics'`).
- Re-entering pages repeated normally. No QML warnings or `ReferenceError`s were logged.
- The Setup page opened from **Game & saves → Setup wizard**.
- No resize or fullscreen toggle was used.
- `QSG_RHI_BACKEND=d3d11` remains the control experiment for the old stall.

This is **launcher-runtime-verified** and **Wine-verified** for the launcher. Windowed mode
at the default size was exercised. Maximized/fullscreen and the 1100x700 minimum layout
were not exercised in this no-window-manager Xvfb session; the QML is anchored and declares
a 1100x700 minimum. Native Windows and Proton were not verified in this session.

### Game launch attempt

An isolated copy of the package was given the user's existing `bin/` (the prebuilt older
`bb-probe.exe` and DLLs) and started from the new launcher. The launcher prepared files,
started Vulkan, and reached GPU initialization. The existing runtime then failed at
`ErrorSurfaceLostKHR` in `vk_swapchain.cpp:227` under the headless Xvfb/Wine display.

This is **not** a successful game-launch verification and **not** a launcher failure. It is
an environment/runtime limitation; the same prebuilt binary also reports
`Unknown present mode FifoRelaxed` because it predates the ported runtime changes. A
native runtime built with MSYS2 CLANG64 is still required to verify the current FIFO
Relaxed/upscaler code. Gameplay was not exercised.

## Proton

Proton 11.0 starts the classic Tk fallback launcher. The Qt Quick path is blocked before
the renderer selection applies: Proton's Wine ICU 68 does not provide the unversioned
`icuuc.dll`/`icuin.dll` that Qt 6.12 imports. This is separate from the D3D11 present bug
and was not changed in this task. No global Proton, Wine, compositor, or system
configuration was modified.

## Diagnostics and environment

- Settings: `%APPDATA%\bbport-launcher\settings.json`; legacy game settings:
  `bbport.ini` in the port/data directory.
- `BB_CONFIG` overrides the settings path; `BB_DATA_DIR` overrides the data directory.
- `BB_LAUNCHER_DEBUG=1` writes launcher/page/window/frame and Qt/QML warnings to
  `%APPDATA%\bbport-launcher\launcher-debug.log`. It is off by default and no per-frame
  logging occurs without it.
- `QSG_RHI_BACKEND` / `QT_QUICK_BACKEND` explicitly chosen by the user are never
  overridden.
- The Diagnostics page shows the port, saves, run-log, and config paths. Use **Copy log**
  or **Save log…** when collecting a report; the session log is capped in the UI at the
  most recent 4000 lines while the copied/exported log remains the full session buffer.

## Known limitations

- The launcher-only test package contains no native runtime.
- Native `bb-probe.exe` from this branch could not be rebuilt on this host.
- The prebuilt older runtime cannot verify the ported `FifoRelaxed` and active-upscaler
  runtime changes.
- Game launch under the headless test display failed at Vulkan surface creation.
- Maximized/fullscreen, native Windows, and Proton Qt Quick were not verified.
- The screenshots in this document are from the Wine/Xvfb test, not from native Windows.
