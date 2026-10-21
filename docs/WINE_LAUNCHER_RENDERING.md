# Wine launcher page-transition fix

## Symptom

Under Wine, advancing the Qt Quick launcher to another page changed the application
state but left the previous frame on screen. Toggling fullscreen forced the new page to
appear. The same state change worked on native Windows.

## Root cause

Wine's Qt Quick **Direct3D11** RHI path does not present a frame for QML visibility
changes. It only presents after a native window event (resize/fullscreen). The QML page
property and the new page's `visible` bindings are evaluated correctly; the scene is
simply never presented.

Evidence from Wine 11.18, PySide6 6.12.0, packaged launcher:

- Default backend: `graphicsApi=Direct3D11`. After clicking a navigation item, the log
  records `QML page=Graphics`, but no present follows; the screen still shows Overview
  until the window is resized or fullscreened.
- `QSG_RENDER_LOOP=basic` does not fix it (the GUI event loop is running; the D3D11
  present path is the problem).
- The bug reproduces on Xvfb with **no window manager**, so Hyprland tiling is not the
  cause.
- `QSG_RHI_BACKEND=opengl` presents immediately: `frame N page='Graphics'` follows the
  page change without any resize.

## Fix

`launcher/bbport_launcher_win.py`:

- `running_under_wine()` detects Wine/Proton via `ntdll!wine_get_version`, with a
  `HKCU\Software\Wine` fallback.
- `configure_renderer()` sets `QSG_RHI_BACKEND=opengl` **only under Wine/Proton**, and
  only when the user has not chosen a backend (`QSG_RHI_BACKEND`/`QT_QUICK_BACKEND`).
- It is called in `main()` before the Qt Quick import and at the top of
  `bbport_launcher_qml.py` before PySide6 is imported.

Native Windows keeps Qt's default (Direct3D11). No repaint timer, page recreation,
fullscreen toggle, or rendering-backend change is applied on native Windows.

The reworked launcher also keeps navigation independent of animation. `Main.qml` switches
pages with plain `visible` bindings; page changes do not wait for a transition to finish
and do not depend on a resize or expose event.

`BB_LAUNCHER_DEBUG=1` additionally writes route/page/window/frame and Qt/QML warnings to
`%APPDATA%\bbport-launcher\launcher-debug.log`; it is off by default.

## Manual regression test

Use a disposable Wine prefix and an Xvfb display so window-manager resizes cannot mask
the bug:

```bash
Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp &
export WINEPREFIX=/tmp/bbport-wine-test DISPLAY=:99 BB_LAUNCHER_DEBUG=1
cd /path/to/bbport-windows
wine Bloodborne.exe --launcher
```

1. Wait for `Main.qml: frame 1 page='Home'` in
   `$WINEPREFIX/drive_c/users/<user>/AppData/Roaming/bbport-launcher/launcher-debug.log`.
2. Click **Graphics** in the left navigation rail.
3. Expect `QML page=Graphics` followed by `frame N page='Graphics'` in the log, with no
   resize/fullscreen.
4. Repeat for **Display**, **Game & saves**, **Mods & patches**, **Online**, **System**,
   **Diagnostics**, and back to **Overview**.
5. To reproduce the old failure, launch with `QSG_RHI_BACKEND=d3d11`: the page log line
   appears, but no frame follows until a resize.

`tests/test_launcher_renderer.py` covers the backend selection and the native-Windows
default without needing Wine.

## Verification notes

- Tested with the reworked packaged launcher: Wine 11.18 (Staging), Windows Python
  3.12.10, PySide6 6.12.0, Xvfb :99 at 1600x1000 with no window manager. The package is
  `out/wine/package/bbport-windows/Bloodborne.exe`; SHA-256
  `4dbd863e40545f26bc5b8c3a1fb37f1b308e679c3eaaa0a3b78af40772a472b6`.
- The packaged launcher rendered the new Overview and each page; every navigation
  produced a following present frame without a resize. The wizard also opened from
  Game & saves. No QML warnings or `ReferenceError`s were logged.
- Windowed mode at 1360x860 was exercised. Maximized/fullscreen and the minimum 1100x700
  layout were not exercised in the no-window-manager Xvfb session. Native Windows and
  Proton Qt Quick were not verified.
- A game launch using the new package plus an isolated copy of an existing older
  `bin/bb-probe.exe` reached Vulkan initialization and then failed at
  `ErrorSurfaceLostKHR` (`vk_swapchain.cpp:227`) under headless Xvfb. That is not a
  launcher regression and not a gameplay verification. The older prebuilt runtime also
  logs `Unknown present mode FifoRelaxed`; it cannot verify the ported `FifoRelaxed` /
  active-upscaler changes. Building the native runtime from this branch still requires
  MSYS2 CLANG64.
- Proton 11.0 starts the classic Tk fallback. Its QML path is blocked before the fix
  applies: Proton's Wine ICU 68 lacks the unversioned `icuuc.dll`/`icuin.dll` that Qt
  6.12 imports. This is a separate Proton/Wine dependency issue, not the D3D11 present
  bug. Native Windows uses the system ICU and is not affected.
- The launcher-only package intentionally has no `bin/bb-probe.exe`; a full package or an
  existing installation's `bin/` is required to start the game.
