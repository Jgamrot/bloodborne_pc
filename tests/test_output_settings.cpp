// SPDX-License-Identifier: GPL-2.0-or-later
#include "bbport_settings.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <chrono>
#include <initializer_list>
#include <map>
#include <string>

int main() {
    using namespace BbSettings;
    const auto path = std::filesystem::temp_directory_path() /
        ("bb-output-settings-" + std::to_string(
            std::chrono::steady_clock::now().time_since_epoch().count()) + ".ini");
#ifdef _WIN32
    _putenv_s("BB_CONFIG", path.string().c_str());
    _putenv_s("BB_RENDER_RES", "");
#else
    setenv("BB_CONFIG", path.string().c_str(), 1);
    unsetenv("BB_RENDER_RES");
#endif
    auto& settings = Get();
    for (const char* size : {"1920x1080", "1920x1200", "1366x768", "3840x1600", "5000x2000", "1080x1920", "1280x800"}) {
        FILE* file = std::fopen(path.string().c_str(), "w");
        assert(file);
        std::fprintf(file, "output_res=%s\n", size);
        std::fclose(file);
        Load();
        int w = 0, h = 0;
        assert(std::sscanf(size, "%dx%d", &w, &h) == 2);
        assert(OutputWidths[settings.output_res] == w && OutputHeights[settings.output_res] == h);
        Save();
        settings.output_res = OutputDefault;
        Load();
        assert(OutputWidths[settings.output_res] == w && OutputHeights[settings.output_res] == h);
    }
    for (const char* bad : {"999999999999999999999x1080", "0x0", "1921x1080",
                           "hello", "1920x1080junk", "+1920x1080", "1920x1080x2"}) {
        FILE* file = std::fopen(path.string().c_str(), "w");
        assert(file);
        std::fprintf(file, "output_res=%s\n", bad);
        std::fclose(file);
        settings.output_res = OutputDefault;
        Load();
        assert(settings.output_res == OutputDefault);
    }
    settings.startup_output_res = OutputDefault;
    settings.output_res = 2; // 2560x1440, same aspect as the startup output.
    assert(!AspectNeedsRestart() && !ResolutionNeedsRestart());
    settings.output_res = 12; // 1920x1200: the in-game 16:10 choice needs a restart.
    assert(OutputWidths[settings.output_res] == 1920 && OutputHeights[settings.output_res] == 1200);
    assert(AspectNeedsRestart() && ResolutionNeedsRestart());
    settings.output_res = 13; // 1366x768: 16:9 to within a pixel, switched to live.
    assert(OutputWidths[settings.output_res] == 1366 && OutputHeights[settings.output_res] == 768);
    assert(!AspectNeedsRestart());
    settings.output_res = 6; // 3440x1440, different camera and HUD aspect.
    assert(AspectNeedsRestart() && ResolutionNeedsRestart());
    // Saving twice writes each key once; repeated keys from older saves collapse to the last value.
    {
        FILE* file = std::fopen(path.string().c_str(), "w");
        assert(file);
        std::fprintf(file, "frame_gen=off\nframe_gen_multiplier=3\nother_tool=1\n"
                           "frame_gen=off\nframe_gen_multiplier=2\nother_tool=2\n");
        std::fclose(file);
        Load();
        Save();
        Save();
        std::map<std::string, int> counts;
        std::string other;
        std::ifstream saved{path};
        for (std::string line; std::getline(saved, line);) {
            const auto eq = line.find('=');
            if (line.empty() || line[0] == '#' || eq == std::string::npos) continue;
            ++counts[line.substr(0, eq)];
            if (line.starts_with("other_tool=")) other = line.substr(eq + 1);
        }
        for (const auto& [key, count] : counts) assert(count == 1);
        assert(counts.contains("frame_gen_fit_display") && other == "2");
        settings.frame_gen_multiplier = 4;
        Load();
        assert(settings.frame_gen_multiplier == 2);
    }
    std::filesystem::remove(path);
    std::puts("Custom output settings: save/load and malformed input rejection PASS");
}
