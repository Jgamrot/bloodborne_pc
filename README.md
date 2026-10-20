# Bloodborne PC (Linux-First Fork)

A stripped, native Linux-first fork of the Bloodborne PC project.

This fork runs your own decrypted copy of Bloodborne (CUSA03173, version 1.09) natively on Linux. The game's code runs directly on x86_64 CPUs, and its graphics are translated through a Vulkan 1.3 renderer.

This project is derived from the work of [Jgamrot](https://github.com/Jgamrot/bloodborne_pc), [Supermedo](https://github.com/Supermedo/bloodborne_pc), [deadinside28](https://github.com/deadinside28/bloodborne_pc), and the [shadPS4](https://github.com/shadps4-emu/shadPS4) project.

> [!IMPORTANT]
> **No game files are included.** You must provide your own decrypted dump of Bloodborne (CUSA03173, patch version 1.09). This project is not affiliated with, endorsed by, or associated with Sony Interactive Entertainment or FromSoftware.

---

## Fork Direction & Divergence

The objective of this fork is to transform the codebase into a genuinely Linux-first product with a clean native GTK4/libadwaita launcher, optimized Vulkan upscaling, and no Windows launcher baggage:

1. **Purged Windows Launcher & Packaging**:
   - Completely eliminated the Windows launcher UI (`bbport_launcher_win.py`, `bbport_launcher_qml.py`, `bbport_launcher_backend.py`, and `launcher/qml/`).
   - Removed Windows packaging and build wrappers (`packaging/windows/`, `.rc` resource files, `.manifest`, Windows-only launcher tests).
   - Removed obsolete Windows translation matrices (`bbport_lang.py`, `bbport_lang_more.py`).
   - Extracted shared online network services and Hunter's Dream account logic into a Linux-native module: [`launcher/bbport_net.py`](launcher/bbport_net.py).
   - Relocated bundled gamepad and keyboard prompt mods into top-level directories: [`bundled/`](bundled/) and [`mods/`](mods/).
   - Preserved third-party licensing in [`licenses/`](licenses/).

2. **Native Linux Experience**:
   - The native GTK4 + libadwaita launcher ([`launcher/bbport_launcher.py`](launcher/bbport_launcher.py)) is the primary, sole supported control surface.
   - Strict XDG compliance for configuration (`~/.config/bbport-launcher/settings.json`), user data, and saves (`~/.local/share/bbport/user/`).
   - Single-command desktop entry installation (`launcher/bbport_launcher.py --install-desktop`) integrating with your Linux application launcher.

3. **Preserved & Verified Internal Resolution Scaling**:
   - Retained the internal render resolution selector alongside output resolution selection.
   - Added real-time internal render resolution and scaling factor calculations in the launcher UI (e.g., rendering at `1280 × 720 (1.5×)` reconstructed to `1920 × 1080`).
   - Full persistence and bidirectional synchronization with `bbport.ini`.

4. **Diagnosed & Fixed Upscaler Performance Bottlenecks**:
   - Resolved the performance regression where enabling an upscaler dropped FPS instead of improving it.
   - Eliminated redundant native proxy resolves, unblocked depth proxy sampling, removed queue-draining barriers, and eliminated synchronous GPU/CPU waits.

---

## Upscaler Bottleneck Diagnosis & Resolution

### The Problem
When enabling temporal upscalers (FSR 3.1, FSR 4, DLSS), users reported that frame rates decreased compared to native rendering, even with lower internal render resolutions selected.

### Root-Cause Analysis
Investigation into the Vulkan rendering pipeline ([`gpu/shadps4/video_core/renderer_vulkan/vk_temporal_upscaler.cpp`](gpu/shadps4/video_core/renderer_vulkan/vk_temporal_upscaler.cpp) and [`gpu/shadps4/video_core/renderer_vulkan/vk_scene_resolution.cpp`](gpu/shadps4/video_core/renderer_vulkan/vk_scene_resolution.cpp)) revealed four critical defects:

1. **Redundant Proxy Resolves on Reduced Resolutions**:
   In `TemporalUpscaler::Run()`, before dispatching the upscaler, `runtime.Transit(&depth)` and `runtime.Transit(&color)` were unconditionally called on the native render targets. When rendering at reduced internal resolution, this forced an unnecessary 1080p color blit and a 9-draw-call depth stencil resample on the GPU every single frame, only for the upscaler immediately following to read the reduced proxy targets directly and discard the resolved native surfaces.
2. **Blocked Depth Proxy Sampling**:
   In `SceneTargets::ProxyCurrent()`, the predicate checked `|| image.info.props.is_depth`, which unconditionally rejected depth proxies from being marked as current. This caused any subsequent pass sampling depth (deferred shading, fog, SSAO) to fall back to the native depth target, continuously re-triggering the expensive 9-draw resolve churn.
3. **Queue-Draining Synchronization Barriers**:
   Vulkan pipeline barriers for motion vectors and output images used `vk::PipelineStageFlagBits2::eAllCommands`. This drained the entire GPU execution pipeline and serialized compute work with graphics passes.
4. **Synchronous CPU Stalls on Sharpening Resizes**:
   `TemporalUpscaler::ExtraSharpen()` executed `scheduler.WaitSubmitted()` on resolution adjustments, blocking the CPU render thread until the GPU became completely idle.

### Changes Implemented
- In `vk_temporal_upscaler.cpp`: Wrapped color and depth target transitions inside `if (!reduced)` so that proxy resolves are completely bypassed during upscaled rendering.
- In `vk_scene_resolution.cpp`: Removed the depth rejection from `ProxyCurrent()` and added proper `vk::ImageLayout::eDepthStencilReadOnlyOptimal` transitions in `PrepareSample()`, allowing shaders to sample reduced depth proxies directly.
- Converted image memory barriers from `eAllCommands` to targeted `eComputeShader` stages.
- Replaced the synchronous `scheduler.WaitSubmitted()` stall with non-blocking deferred destruction via `scheduler.DeferOperation()`.

> [!NOTE]
> **Performance Caveat**: Automated unit and rendering tests verify that the redundant resolves, CPU stalls, and barrier serializations have been eliminated. However, temporal upscalers incur compute dispatch overhead and reconstruct from internal targets. In CPU-bound scenes or on low-end GPUs where compute execution exceeds pixel shader savings, upscaling may not increase FPS. In-game comparative performance across gameplay scenes has not been empirically benchmarked.

---

## Graphics Configuration & Scaling

### Render Resolution vs. Output Resolution

- **Output Resolution** (`output_res` in `bbport.ini`):
  The target resolution presented to your display:
  - 1280×720 (Steam Deck / 720p)
  - 1920×1080 (1080p Standard)
  - 2560×1440 (1440p QHD)
  - 3840×2160 (4K UHD)
  - Ultrawide formats: 2560×1080, 3440×1440, 3840×1600, 5120×1440.

- **Internal Resolution Presets** (`preset` in `bbport.ini`):
  Controls the internal render target dimensions before upscaler reconstruction:
  - **Native AA** (`0`): 1.0× scaling (renders internally at full output resolution).
  - **Quality** (`1`): 1.5× scale factor (e.g., 1080p → 1280×720; 1440p → 1706×960; 4K → 2560×1440).
  - **Balanced** (`2`): 1.7× scale factor (e.g., 1080p → 1130×636; 4K → 2258×1270).
  - **Performance** (`3`): 2.0× scale factor (e.g., 1080p → 960×540; 4K → 1920×1080).
  - **Ultra Performance** (`4`): 3.0× scale factor (e.g., 1080p → 640×360; 4K → 1280×720).

- **Supported Upscalers** (`upscaler` in `bbport.ini`):
  - `fsr4`: AMD FidelityFX Super Resolution 4 (best quality on GPUs with INT8 fast dot product support).
  - `fsr411`: AMD FSR 4.1.1.
  - `fsr3`: AMD FSR 3.1 (universal compatibility across AMD, Intel, and NVIDIA).
  - `dlss`: NVIDIA DLSS (requires NVIDIA GeForce RTX series).
  - `taa`: Native-resolution Temporal Anti-Aliasing (preset selector automatically reflects native resolution).
  - `off`: Unfiltered output.

- **Post-Processing & Sharpening**:
  - RCAS Sharpening (`sharpen=1` and `sharpness=0.00` to `1.00`).
  - Object Motion Vectors (`object_motion=1`).
  - Live Resolution (`live_resolution=0` for maximum speed via start-up patch, `1` for live dynamic switching).

---

## Requirements

### Operating System & Dependencies
- Linux x86_64 (glibc-based distributions: Ubuntu 22.04+, Fedora 38+, Arch Linux, etc.).
- Graphics card with **Vulkan 1.3** and `VK_KHR_dynamic_rendering` support (Mesa RADV/ANV, or proprietary NVIDIA driver 535+).
- Python 3.10+ with `PyGObject` (`gi`), `GTK4`, and `libadwaita`.
- Vulkan development headers, Clang/LLVM or GCC, CMake 3.22+, and Ninja (for compiling).

### CPU Requirements
- Intel Core 4th generation (Haswell, 2013) or newer, or AMD Ryzen.
- The game requires AVX, BMI1, MOVBE, and LZCNT instructions. CPUs lacking AVX cannot execute the port.

---

## Building and Running

### 1. Build the Native Port
Clone the repository recursively with submodules:
```bash
git clone --recursive https://github.com/NotBhan/bloodborne_pc_notbhan.git
cd bloodborne_pc_notbhan
```

Compile the Vulkan runtime, loader, and C tools:
```bash
./build.sh
```

To run all native C/C++ unit tests (allocator, memory, pad, semaphores, frame limiter, scene resolution, upscaler fallback):
```bash
./build.sh --test
```

### 2. Launch the Native Launcher
Launch the GTK4 launcher interface:
```bash
./launcher/bb-launcher.sh
```
Or directly via Python:
```bash
python3 launcher/bbport_launcher.py
```

To install the desktop shortcut into `~/.local/share/applications`:
```bash
python3 launcher/bbport_launcher.py --install-desktop
```

### 3. Direct Command-Line Launch
You can also bypass the GUI launcher and execute the game directly:
```bash
./run.sh --app0 /path/to/CUSA03173
```

---

## Configuration & Persistence

Configuration is strictly divided between user environment preferences and in-engine settings:

1. **Launcher Settings** (`~/.config/bbport-launcher/settings.json`):
   - `game_dir`: Path to extracted `CUSA03173` directory containing `eboot.bin`.
   - `user_dir`: Saves and trophy folder (defaults to `~/.local/share/bbport/user/`).
   - `mods_dir` & `mods_enabled`: Mods directory and toggle.
   - `control_scheme`: `xbox`, `pc` (keyboard/mouse with PCBButtons prompts), or `playstation`.
   - `fps_mode` & `fps_limit`: Uncapped or capped frame limits.
   - `present_mode`: Vulkan presentation mode (`Mailbox`, `Fifo`, `FifoRelaxed`, `Immediate`).
   - `fullscreen`: Fullscreen toggle.
   - `mangohud`: Integration with MangoHud overlay.

2. **Game Engine Settings** (`bbport.ini`):
   - `upscaler`: `fsr3`, `fsr4`, `fsr411`, `dlss`, `taa`, or `off`.
   - `preset`: `0` (Native), `1` (Quality), `2` (Balanced), `3` (Performance), `4` (Ultra Performance).
   - `output_res`: Output resolution string (e.g., `1920x1080`, `2560x1440`, `3840x2160`).
   - `sharpen` & `sharpness`: RCAS sharpening settings.
   - `effect_*`: Toggles for chromatic aberration, depth of field, motion blur, SSAO, dynamic shadows, SSR.
   - `pc_*`: Optional enhancements (lamp level up/storage, rebirth, mirror appearance, two invaders).

---

## Testing & Validation Suite

Run all validation test suites:

```bash
# 1. Native C/C++ engine, Vulkan, and math tests:
./build.sh --test

# 2. Python launcher, network, mod, and patch tests:
python3 -m unittest discover tests
```

- **Linux Launcher Tests** ([`tests/test_launcher_linux.py`](tests/test_launcher_linux.py)):
  Validates GTK4/Adw row generation, XDG path resolution, INI roundtrips, atomic writes, control scheme switching, FSR support probing, internal resolution calculations, and UI subtitle updates.
- **Scene Resolution & Upscaler Fallback Tests** ([`tests/test_scene_resolution.cpp`](tests/test_scene_resolution.cpp), [`tests/test_upscaler_support.cpp`](tests/test_upscaler_support.cpp)):
  Validates Vulkan target proxies, stencil preservation, downscaling math, and dynamic FSR/DLSS device fallbacks on Vulkan (runs headlessly via Lavapipe).

---

## Retained Upstream Attribution & Licenses

This fork builds upon foundational work from the open-source community:

- **[Supermedo](https://github.com/Supermedo/bloodborne_pc)** (Mohammed Albarghouthi) for the initial PC port.
- **[deadinside28](https://github.com/deadinside28/bloodborne_pc)** for `bbport`.
- **[shadPS4 Team](https://github.com/shadps4-emu/shadPS4)** for the PlayStation 4 recompiler and Vulkan translation layers.
- **[droogie](https://github.com/droogie/bbhost)** for in-engine PC menus, enhancements, and keyboard prompt systems.
- **[Awaken](https://github.com/Awakenchan/BloodBorneButPc)**, **[The Hunter's Dream Team](https://thehuntersdream.com)**, and **[Wozzardman](https://github.com/Wozzardman/shadp2p)** for online backend and multiplayer adaptation.
- **[MikeTat1988](https://github.com/MikeTat1988/HuntersAtlas)** for Hunter's Atlas (GPL-2.0).
- **[AzaharPlus](https://github.com/AzaharPlus/shadPS4Plus)** for PkgExtractor (GPL-2.0).
- **Dommo** for Xbox prompts ([Nexus Mods #30](https://www.nexusmods.com/bloodborne/mods/30)).
- **JinkiJinn** for PCBButtons keyboard prompts ([Nexus Mods #460](https://www.nexusmods.com/bloodborne/mods/460)).

All third-party licenses are preserved in [`licenses/`](licenses/) and [`LICENSE`](LICENSE).
