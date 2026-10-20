// SPDX-License-Identifier: GPL-2.0-or-later
#include "bbport_settings.h"

#include <algorithm>
#include <charconv>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>
#include <filesystem>
#include <fstream>
#include <nlohmann/json.hpp>

namespace BbSettings {

namespace {

const char* Path() {
    const char* env = std::getenv("BB_CONFIG");
    return env && env[0] ? env : "bbport.ini";
}

float Clamp(float v, float lo, float hi) {
    return std::clamp(v, lo, hi);
}

void Set(Values& v, const std::string& key, const std::string& value) {
    const float f = float(std::atof(value.c_str()));
    const int i = std::atoi(value.c_str());
    if (key == "upscaler") {
        for (int u = 0; u < UpscalerCount; ++u) {
            if (value == UpscalerName(u)) {
                v.upscaler = u;
            }
        }
    } else if (key == "frame_gen") {
        for (int g = 0; g < FrameGenCount; ++g) {
            if (value == FrameGenName(g)) {
                v.frame_gen = g;
            }
        }
    } else if (key == "frame_gen_multiplier") {
        v.frame_gen_multiplier = std::clamp(i, 2, 4);
    } else if (key == "frame_gen_fit_display") {
        v.frame_gen_fit_display = i != 0;
    } else if (key == "preset") {
        v.preset = std::clamp(i, 0, PresetCount - 1);
    } else if (key == "sharpen") {
        v.sharpen = i != 0;
    } else if (key == "sharpness") {
        v.sharpness = Clamp(f, 0.0f, 2.0f);
    } else if (key == "jitter") {
        v.jitter = i != 0;
    } else if (key == "reactive") {
        v.reactive = i != 0;
    } else if (key == "object_motion") {
        v.object_motion = i != 0 && v.object_motion_supported.load();
    } else if (key == "reactive_scale") {
        v.reactive_scale = Clamp(f, 0.0f, 16.0f);
    } else if (key == "reactive_threshold") {
        v.reactive_threshold = Clamp(f, 0.0f, 1.0f);
    } else if (key == "reactive_max") {
        v.reactive_max = Clamp(f, 0.0f, 1.0f);
    } else if (key == "debug_view") {
        v.debug_view = std::clamp(i, 0, DebugViewCount - 1);
    } else if (key == "show_fps") {
        v.show_fps = i != 0;
    } else if (key == "fsr4_auto_exposure") {
        v.fsr4_auto_exposure = i != 0;
    } else if (key == "fsr4_invert_jitter") {
        v.fsr4_invert_jitter = i != 0;
    } else if (key == "mouse_camera") {
        v.mouse_camera = i != 0;
    } else if (key == "mouse_sensitivity") {
        v.mouse_sensitivity = std::clamp(i, 1, 50);
    } else if (key == "mouse_invert_y") {
        v.mouse_invert_y = i != 0;
    } else if (key == "mouse_menu") {
        v.mouse_menu = i != 0;
    } else if (key == "model_lod") {
        v.model_lod = std::clamp(i, -2, 2);
    } else if (key == "live_resolution") {
        v.live_resolution = value == "auto" ? -1 : std::clamp(i, 0, 1);
    } else if (key == "output_res") {
        for (int r = 0; r < OutputCustom; ++r) {
            if (value == std::to_string(OutputWidths[r]) + "x" + std::to_string(OutputHeights[r])) {
                v.output_res = r;
                return;
            }
        }
        const auto separator = value.find('x');
        if (separator == std::string::npos) return;
        int w = 0, h = 0;
        const char* begin = value.data();
        const char* split = begin + separator;
        const char* end = begin + value.size();
        const auto width = std::from_chars(begin, split, w);
        const auto height = std::from_chars(split + 1, end, h);
        if (width.ec == std::errc{} && width.ptr == split &&
            height.ec == std::errc{} && height.ptr == end &&
            w >= 256 && w <= 7680 && h >= 144 && h <= 4320 && !(w & 1) && !(h & 1)) {
            OutputWidths[OutputCustom] = w;
            OutputHeights[OutputCustom] = h;
            v.output_res = OutputCustom;
        }
    } else {
        for (int e = 0; e < EffectCount; ++e) {
            if (key == Effects[e].key) {
                v.effects[e] = i != 0;
            }
        }
    }
}

} // namespace

Values& Get() {
    static Values values;
    return values;
}

void Load() {
    auto& v = Get();
    for (int e = 0; e < EffectCount; ++e) {
        v.effects[e] = Effects[e].default_on;
    }
    if (FILE* file = std::fopen(Path(), "r")) {
        char line[256];
        while (std::fgets(line, sizeof(line), file)) {
            std::string text{line};
            text.erase(text.find_last_not_of(" \t\r\n") + 1);
            const auto eq = text.find('=');
            if (text.empty() || text[0] == '#' || eq == std::string::npos) {
                continue;
            }
            Set(v, text.substr(0, eq), text.substr(eq + 1));
        }
        std::fclose(file);
        std::printf("Settings: %s\n", Path());
    }
    // Environment overrides (scripts, A/B tests).
    if (const char* env = std::getenv("BB_UPSCALER")) {
        v.upscaler = UpscalerOff;
        for (int u = 0; u < UpscalerCount; ++u) {
            if (std::strcmp(env, UpscalerName(u)) == 0) v.upscaler = u;
        }
    }
    const std::pair<const char*, const char*> env_keys[] = {
        {"BB_FSR_SHARPNESS", "sharpness"},        {"BB_JITTER", "jitter"},
        {"BB_REACTIVE", "reactive"},              {"BB_REACTIVE_SCALE", "reactive_scale"},
        {"BB_REACTIVE_THRESHOLD", "reactive_threshold"}, {"BB_REACTIVE_MAX", "reactive_max"},
        {"BB_UPSCALE_PRESET", "preset"},            {"BB_OBJECT_MOTION", "object_motion"},
        {"BB_PC_MIRROR", "pc_mirror_appearance"},   {"BB_PC_TWO_INVADERS", "pc_two_invaders"},
        {"BB_PC_REBIRTH", "pc_rebirth"},           {"BB_MOUSE_CAMERA", "mouse_camera"},
        {"BB_PC_LAMPS", "pc_enhanced_lamps"},
        {"BB_OUTPUT_RES", "output_res"},
        {"BB_MOUSE_MENU", "mouse_menu"},
        {"BB_FRAME_GEN", "frame_gen"},              {"BB_FRAME_GEN_MULTIPLIER", "frame_gen_multiplier"},
        {"BB_FRAME_GEN_FIT_DISPLAY", "frame_gen_fit_display"},
    };
    for (const auto& [env, key] : env_keys) {
        if (const char* value = std::getenv(env)) {
            Set(v, key, value);
        }
    }
    // The window mode is the launcher's setting, passed at start.
    const char* fullscreen = std::getenv("BB_FULLSCREEN");
    v.fullscreen = fullscreen && fullscreen[0] == '1';
    v.startup_preset = v.preset;
    v.startup_upscaler = v.upscaler;
    v.startup_object_motion = v.object_motion;
    for (int e = 0; e < EffectCount; ++e) {
        v.startup_effects[e] = v.effects[e];
    }
    v.startup_model_lod = v.model_lod;
    v.startup_output_res = v.output_res;
    v.startup_live_resolution = v.live_resolution;
    v.active_upscaler = v.upscaler.load();
    v.upscaler_fallback_reason = nullptr;
}

void ConfigureUpscalerSupport(bool fsr4, bool fsr411) {
    auto& v = Get();
    v.fsr4_supported = fsr4;
    v.fsr411_supported = fsr4 && fsr411;
    const int requested = v.upscaler;
    if ((requested == UpscalerFsr4 && !v.fsr4_supported) ||
        (requested == UpscalerFsr411 && !v.fsr411_supported)) {
        v.fsr4_problem = "GPU lacks required FSR 4 shader features; falling back to FSR 3.1";
        v.upscaler_fallback_reason = "GPU lacks required FSR 4 shader features; falling back to FSR 3.1";
        std::printf("Upscaler: %s unsupported on this GPU; using FSR 3.1 fallback before the first frame\n",
                    UpscalerName(requested));
        v.active_upscaler = UpscalerFsr3;
    } else {
        v.active_upscaler = requested;
        v.upscaler_fallback_reason = nullptr;
    }
}

void ConfigureObjectMotionSupport(bool supported, const char* problem) {
    auto& v = Get();
    static std::string kept;
    kept = problem ? problem : "";
    v.object_motion_supported = supported;
    v.object_motion_problem = supported || kept.empty() ? nullptr : kept.c_str();
    if (!supported) {
        v.object_motion = false;
        v.startup_object_motion = false; // no "restart to apply" for a path that cannot run
    }
}

void ConfigureDlssSupport(bool available, const char* problem) {
    auto& v = Get();
    v.dlss_supported = available;
    static std::string kept;
    kept = problem ? problem : "";
    v.dlss_problem = available || kept.empty() ? nullptr : kept.c_str();
    if (v.upscaler == UpscalerDlss && !available) {
        v.upscaler_fallback_reason = "DLSS unavailable on this hardware; falling back to FSR 3.1";
        std::printf("Upscaler: DLSS unavailable (%s); using FSR 3.1 fallback\n",
                    kept.empty() ? "bbport_dlss.dll or nvngx_dlss.dll missing" : kept.c_str());
        v.active_upscaler = UpscalerFsr3;
    } else if (v.upscaler == UpscalerDlss) {
        v.active_upscaler = UpscalerDlss;
        v.upscaler_fallback_reason = nullptr;
    }
}

bool FixedRenderSession() {
    const char* size = std::getenv("BB_RENDER_RES");
    return size && size[0];
}

int RenderPreset() {
    const auto& v = Get();
    return FixedRenderSession() ? v.startup_preset :
        v.upscaler == UpscalerTaa ? NativeAA : v.preset.load();
}

bool AspectNeedsRestart() {
    const auto& v = Get();
    const int a = v.output_res, b = v.startup_output_res;
    return int64_t(OutputWidths[a]) * OutputHeights[b] !=
           int64_t(OutputWidths[b]) * OutputHeights[a];
}

bool ResolutionNeedsRestart() {
    const auto& v = Get();
    // TAA needs the live path (native guest targets): run.sh selects it on restart.
    return AspectNeedsRestart() || (FixedRenderSession() &&
        (v.preset != v.startup_preset || v.output_res != v.startup_output_res ||
         (v.upscaler == UpscalerOff) != (v.startup_upscaler == UpscalerOff) ||
         (v.upscaler == UpscalerTaa) != (v.startup_upscaler == UpscalerTaa)));
}

void Save() {
    const auto& v = Get();
    // Lines this function does not write (keys other tools own, such as pc_menu) are kept.
    std::vector<std::string> kept;
    if (FILE* old = std::fopen(Path(), "r")) {
        char line[256];
        while (std::fgets(line, sizeof(line), old)) {
            std::string text{line};
            text.erase(text.find_last_not_of(" \t\r\n") + 1);
            const auto eq = text.find('=');
            if (text.empty() || text[0] == '#' || eq == std::string::npos) continue;
            const std::string key = text.substr(0, eq);
            bool ours = false;
            for (const char* name : {"upscaler", "preset", "sharpen", "sharpness", "jitter", "reactive",
                                     "object_motion", "reactive_scale", "reactive_threshold", "reactive_max",
                                     "debug_view", "show_fps", "fsr4_auto_exposure", "fsr4_invert_jitter",
                                     "model_lod", "output_res", "live_resolution",
                                     "mouse_camera", "mouse_sensitivity", "mouse_invert_y", "mouse_menu"}) {
                ours |= key == name;
            }
            for (int e = 0; e < EffectCount; ++e) ours |= key == Effects[e].key;
            if (!ours) kept.push_back(text);
        }
        std::fclose(old);
    }
    FILE* file = std::fopen(Path(), "w");
    if (!file) {
        std::printf("Settings: cannot write %s\n", Path());
        return;
    }
    std::fprintf(file,
                 "# bbport settings (in-game menu: Insert / L3+R3)\n"
                 "upscaler=%s\npreset=%d\nsharpen=%d\nsharpness=%.2f\njitter=%d\n"
                 "reactive=%d\nobject_motion=%d\nreactive_scale=%.2f\nreactive_threshold=%.2f\nreactive_max=%.2f\n"
                 "debug_view=%d\nshow_fps=%d\nfsr4_auto_exposure=%d\nfsr4_invert_jitter=%d\n",
                 UpscalerName(v.upscaler), v.preset.load(), int(v.sharpen.load()),
                 v.sharpness.load(), int(v.jitter.load()), int(v.reactive.load()),
                 int(v.object_motion.load()),
                 v.reactive_scale.load(), v.reactive_threshold.load(), v.reactive_max.load(),
                 v.debug_view.load(), int(v.show_fps.load()),
                 int(v.fsr4_auto_exposure.load()), int(v.fsr4_invert_jitter.load()));
    std::fprintf(file, "mouse_camera=%d\nmouse_sensitivity=%d\nmouse_invert_y=%d\nmouse_menu=%d\n",
                 int(v.mouse_camera.load()), v.mouse_sensitivity.load(), int(v.mouse_invert_y.load()),
                 int(v.mouse_menu.load()));
    // Read by patches.py at start.
    for (int e = 0; e < EffectCount; ++e) {
        std::fprintf(file, "%s=%d\n", Effects[e].key, int(v.effects[e].load()));
    }
    std::fprintf(file, "frame_gen=%s\nframe_gen_multiplier=%d\nframe_gen_fit_display=%d\n",
                 FrameGenName(v.frame_gen), v.frame_gen_multiplier.load(),
                 int(v.frame_gen_fit_display.load()));
    std::fprintf(file, "model_lod=%d\noutput_res=%dx%d\n", v.model_lod.load(),
                 OutputWidths[v.output_res], OutputHeights[v.output_res]);
    // Read by run.sh at start.
    std::fprintf(file, "live_resolution=%s\n", v.live_resolution < 0 ? "auto"
                                                  : v.live_resolution ? "1" : "0");
    for (const std::string& line : kept) {
        std::fprintf(file, "%s\n", line.c_str());
    }
    std::fclose(file);
}

// The in-game PC menu (src/pc_menu.c) reads and writes the same settings through these.
namespace {
// A setting as the in-game PC menu sees it: on/off as 0/1, the upscaler as its index, the
// output resolution as an index into OutputWidths, live resolution as -1 (auto), 0 or 1, the
// model detail as -2..2. False for a key the menu does not handle.
bool Read(const Values& v, const std::string& k, int& out) {
    if (k == "show_fps") out = v.show_fps.load();
    else if (k == "fullscreen") out = v.fullscreen.load();
    else if (k == "sharpen") out = v.sharpen.load();
    else if (k == "jitter") out = v.jitter.load();
    else if (k == "object_motion") out = v.object_motion.load();
    else if (k == "upscaler") out = v.upscaler.load();
    else if (k == "preset") out = v.preset.load();
    else if (k == "output_res") out = v.output_res.load();
    else if (k == "live_resolution") out = v.live_resolution.load();
    else if (k == "model_lod") out = v.model_lod.load();
    else if (k == "mouse_camera") out = v.mouse_camera.load();
    else if (k == "mouse_sensitivity") out = v.mouse_sensitivity.load();
    else if (k == "mouse_invert_y") out = v.mouse_invert_y.load();
    else if (k == "mouse_menu") out = v.mouse_menu.load();
    else {
        for (int e = 0; e < EffectCount; ++e) {
            if (k == Effects[e].key) {
                out = v.effects[e].load();
                return true;
            }
        }
        return false;
    }
    return true;
}
} // namespace

// The in-game PC menu (src/pc_menu.c) reads and writes the same settings through these.
extern "C" int bbgpu_setting_get(const char* key, int* value) {
    return Read(Get(), key, *value) ? 1 : 0;
}

extern "C" int bbgpu_setting_default(const char* key, int* value) {
    const std::string k = key;
    for (int e = 0; e < EffectCount; ++e) {
        if (k == Effects[e].key) {
            *value = Effects[e].default_on;
            return 1;
        }
    }
    static const Values defaults;
    return Read(defaults, k, *value) ? 1 : 0;
}

namespace {
// Fullscreen belongs to the launcher (settings.json, passed as BB_FULLSCREEN): the window
// follows the setting at once (window.cpp), a restart inherits the environment, and the
// launcher's file keeps it for the next start.
void SetFullscreen(bool on) {
    Get().fullscreen = on;
#ifdef _WIN32
    _putenv_s("BB_FULLSCREEN", on ? "1" : "0");
#else
    setenv("BB_FULLSCREEN", on ? "1" : "0", 1);
#endif
#ifdef _WIN32
    const char* appdata = std::getenv("APPDATA");
    if (!appdata) return;
    const std::filesystem::path file = std::filesystem::path(appdata) / "bbport-launcher" / "settings.json";
#else
    // The same directory as launcher/bbport_launcher.py (XDG_CONFIG_HOME or ~/.config).
    const char* config = std::getenv("XDG_CONFIG_HOME");
    std::filesystem::path directory;
    if (config && config[0]) {
        directory = config;
    } else {
        const char* home = std::getenv("HOME");
        if (!home || !home[0]) return;
        directory = std::filesystem::path(home) / ".config";
    }
    const std::filesystem::path file = directory / "bbport-launcher" / "settings.json";
#endif
    std::ifstream in(file);
    if (!in) return;
    nlohmann::json root = nlohmann::json::parse(in, nullptr, false);
    in.close();
    if (!root.is_object()) return;
    root["fullscreen"] = on;
    const auto part = file.string() + ".part";
    {
        std::ofstream out(part, std::ios::trunc);
        out << root.dump(2);
        if (!out) return;
    }
    std::error_code error;
    std::filesystem::rename(part, file, error);
}
} // namespace

extern "C" void bbgpu_setting_set(const char* key, int value) {
    const std::string k = key;
    if (k == "fullscreen") {
        SetFullscreen(value != 0);
        return;
    }
    std::string text = std::to_string(value);
    if (k == "upscaler") {
        text = UpscalerName(value);
        Get().active_upscaler = value;
        Get().upscaler_fallback_reason = nullptr;
    } else if (k == "output_res") {
        const int r = std::clamp(value, 0, OutputCount - 1);
        text = std::to_string(OutputWidths[r]) + "x" + std::to_string(OutputHeights[r]);
    } else if (k == "live_resolution" && value < 0) {
        text = "auto";
    }
    Set(Get(), k, text);
    Save();
}

extern "C" void bbgpu_settings_save(void) {
    BbSettings::Save();
}

extern "C" int bbgpu_active_upscaler(void) {
    return BbSettings::Get().active_upscaler.load();
}

extern "C" const char* bbgpu_upscaler_fallback_reason(void) {
    return BbSettings::Get().upscaler_fallback_reason.load();
}

// Whether this GPU runs an upscaler (the menu offers only those).
extern "C" int bbgpu_upscaler_supported(int upscaler) {
    const auto& v = Get();
    switch (upscaler) {
    case UpscalerFsr4: return v.fsr4_supported.load();
    case UpscalerFsr411: return v.fsr411_supported.load();
    case UpscalerDlss: return v.dlss_supported.load();
    default: return upscaler >= 0 && upscaler < UpscalerCount;
    }
}

float PresetScale(int preset) {
    static constexpr float scales[PresetCount] = {1.0f, 1.5f, 1.7f, 2.0f, 3.0f};
    return scales[std::clamp(preset, 0, PresetCount - 1)];
}

const char* PresetName(int preset) {
    static constexpr const char* names[PresetCount] = {"Native AA", "Quality", "Balanced",
                                                       "Performance", "Ultra Performance"};
    return names[std::clamp(preset, 0, PresetCount - 1)];
}

const char* FrameGenName(int frame_gen) {
    static constexpr const char* names[FrameGenCount] = {"off", "fsr3", "dlss"};
    return names[std::clamp(frame_gen, 0, FrameGenCount - 1)];
}

const char* UpscalerName(int upscaler) {
    static constexpr const char* names[UpscalerCount] = {"off", "fsr3", "fsr4", "fsr411", "taa", "dlss"};
    return names[std::clamp(upscaler, 0, UpscalerCount - 1)];
}

} // namespace BbSettings
