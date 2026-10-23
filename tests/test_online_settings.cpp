// SPDX-License-Identifier: GPL-2.0-or-later
// Online (BB_ONLINE=1), the cheats, the free camera and the debug menu read as off and the in-game
// PC menu cannot turn them on; bbport.ini keeps the player's choice for offline play.
#include "bbport_settings.h"
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

extern "C" int bbgpu_setting_get(const char* key, int* value);
extern "C" void bbgpu_setting_set(const char* key, int value);

namespace {
int Setting(const char* key) {
    int value = -1;
    assert(bbgpu_setting_get(key, &value));
    return value;
}

int Index(const char* key) {
    for (int e = 0; e < BbSettings::EffectCount; ++e)
        if (!std::strcmp(BbSettings::Effects[e].key, key)) return e;
    assert(false);
    return -1;
}
} // namespace

int main() {
    using namespace BbSettings;
    const auto path = std::filesystem::temp_directory_path() /
        ("bb-online-settings-" + std::to_string(
            std::chrono::steady_clock::now().time_since_epoch().count()) + ".ini");
#ifdef _WIN32
    _putenv_s("BB_CONFIG", path.string().c_str());
    _putenv_s("BB_ONLINE", "1");
#else
    setenv("BB_CONFIG", path.string().c_str(), 1);
    setenv("BB_ONLINE", "1", 1);
#endif
    {
        std::ofstream file(path);
        file << "cheat_no_stamina=1\ncheat_stamina_out_of_combat=1\ndebug_camera=1\n"
                "tweak_no_rally=1\npc_two_invaders=1\n";
    }
    Load();
    assert(Online());
    for (const char* key : {"cheat_no_stamina", "cheat_stamina_out_of_combat", "debug_camera",
                            "debug_menu", "cheat_no_death"}) {
        assert(OnlineBlocked(Index(key)));
        assert(Setting(key) == 0);
    }
    // The stored choice stays for offline play.
    assert(Get().effects[Index("cheat_no_stamina")]);
    assert(Get().effects[Index("debug_camera")]);
    // Tweaks and PC enhancements are not cheats.
    assert(!OnlineBlocked(Index("tweak_no_rally")) && Setting("tweak_no_rally") == 1);
    assert(!OnlineBlocked(Index("pc_two_invaders")) && Setting("pc_two_invaders") == 1);
    // The PC menu cannot switch a cheat on (or off) while online.
    bbgpu_setting_set("cheat_no_death", 1);
    bbgpu_setting_set("cheat_no_stamina", 0);
    assert(!Get().effects[Index("cheat_no_death")]);
    assert(Get().effects[Index("cheat_no_stamina")]);
    std::stringstream saved;
    saved << std::ifstream(path).rdbuf();
    assert(saved.str().find("cheat_no_death=1") == std::string::npos);
    // Other settings still save.
    bbgpu_setting_set("tweak_no_rally", 0);
    assert(Setting("tweak_no_rally") == 0);
    std::filesystem::remove(path);
    std::puts("online settings: ok");
}
