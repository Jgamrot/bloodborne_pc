// SPDX-License-Identifier: GPL-2.0-or-later
// bbport: the object-motion capability gate. The renderer refuses object motion on AMD GPUs
// before RDNA3; the setting must then read off everywhere (menu, overlay, bbport.ini) and a
// later config/environment value must not turn it back on.
#include "bbport_settings.h"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>

extern "C" int bbgpu_setting_get(const char* key, int* value);

namespace {

void WriteIni(const std::filesystem::path& path, const char* object_motion) {
    std::ofstream file(path, std::ios::trunc);
    file << "upscaler=fsr3\n";
    file << "object_motion=" << object_motion << '\n';
}

int ReadSetting(const char* key) {
    int value = -1;
    assert(bbgpu_setting_get(key, &value));
    return value;
}

} // namespace

int main() {
    using namespace BbSettings;

    unsetenv("BB_OBJECT_MOTION");
    const auto dir = std::filesystem::temp_directory_path() / "bbport-settings-test";
    std::filesystem::remove_all(dir);
    std::filesystem::create_directories(dir);
    const auto ini = dir / "bbport.ini";
    setenv("BB_CONFIG", ini.c_str(), 1);

    // Supported: the file's value is honoured.
    ConfigureObjectMotionSupport(true, nullptr);
    WriteIni(ini, "1");
    Load();
    assert(Get().object_motion.load());
    assert(Get().object_motion_supported.load());
    assert(Get().object_motion_problem.load() == nullptr);
    assert(ReadSetting("object_motion") == 1);

    // Refused: the setting is cleared now, and both the file and the menu are refused.
    ConfigureObjectMotionSupport(false, "test GPU loses the device");
    assert(!Get().object_motion.load());
    assert(!Get().object_motion_supported.load());
    assert(!Get().startup_object_motion);
    assert(Get().object_motion_problem.load() != nullptr);
    assert(std::string(Get().object_motion_problem.load()) == "test GPU loses the device");
    assert(ReadSetting("object_motion") == 0);

    WriteIni(ini, "1");
    Load();
    assert(!Get().object_motion.load());
    assert(ReadSetting("object_motion") == 0);

    // A refused capability is written back off, so the next start does not ask for a restart.
    Save();
    {
        std::ifstream file(ini);
        std::string text((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        assert(text.find("object_motion=0") != std::string::npos);
    }

    // AMD RDNA 2 risk: the menu may write an explicit opt-in, which survives the next Load and
    // is saved as 1 so the restart (when the renderer runs it) starts with object motion on.
    ConfigureObjectMotionSupport(false, "AMD RDNA 2 risk", true);
    assert(!Get().object_motion.load());
    assert(ReadSetting("object_motion") == 0);
    WriteIni(ini, "1");
    Load();
    assert(Get().object_motion.load());
    assert(ReadSetting("object_motion") == 1);
    Save();
    {
        std::ifstream file(ini);
        std::string text((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        assert(text.find("object_motion=1") != std::string::npos);
    }

    // A hard refusal (missing device feature, allocation failure) still wins over the opt-in.
    ConfigureObjectMotionSupport(false, "no vertex stores", false);
    assert(!Get().object_motion.load());
    WriteIni(ini, "1");
    Load();
    assert(!Get().object_motion.load());
    assert(ReadSetting("object_motion") == 0);

    // Supported again: the value can be turned on.
    ConfigureObjectMotionSupport(true, nullptr);
    WriteIni(ini, "1");
    Load();
    assert(Get().object_motion.load());
    assert(Get().object_motion_problem.load() == nullptr);

    // Upscaler fallback distinction tests:
    // 1. FSR 4 requested on unsupported hardware falls back to FSR 3.1 runtime active
    Get().upscaler = UpscalerFsr4;
    ConfigureUpscalerSupport(false, false);
    assert(Get().upscaler.load() == UpscalerFsr4); // requested preserved
    assert(Get().active_upscaler.load() == UpscalerFsr3); // active is FSR 3.1
    assert(Get().upscaler_fallback_reason.load() != nullptr);
    assert(std::string(Get().upscaler_fallback_reason.load()).find("FSR 3.1") != std::string::npos);

    // 2. FSR 4 supported retains FSR 4 active
    ConfigureUpscalerSupport(true, false);
    assert(Get().upscaler.load() == UpscalerFsr4);
    assert(Get().active_upscaler.load() == UpscalerFsr4);
    assert(Get().upscaler_fallback_reason.load() == nullptr);

    // 3. DLSS requested on non-NVIDIA falls back to FSR 3.1 runtime active
    Get().upscaler = UpscalerDlss;
    ConfigureDlssSupport(false, "no NVIDIA RTX GPU found");
    assert(Get().upscaler.load() == UpscalerDlss); // requested preserved
    assert(Get().active_upscaler.load() == UpscalerFsr3); // active is FSR 3.1
    assert(Get().upscaler_fallback_reason.load() != nullptr);

    std::filesystem::remove_all(dir);
    std::puts("PASS: object-motion capability gate and upscaler fallback distinction");
    return 0;
}
