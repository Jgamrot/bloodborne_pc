// SPDX-License-Identifier: GPL-2.0-or-later
// Saved FSR 4 choices must be safe before the first rendered frame on older GPUs.
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <unistd.h>
#include "bbport_settings.h"

int main() {
    using namespace BbSettings;
    char path[] = "/tmp/bbport-upscaler-test-XXXXXX";
    const int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);
    setenv("BB_CONFIG", path, 1);
    unsetenv("BB_UPSCALER");
    unsetenv("BB_UPSCALE_PRESET");
    unsetenv("BB_RENDER_RES");
    auto& s = Get();
    s.upscaler = UpscalerTaa;
    s.preset = Performance;
    assert(RenderPreset() == NativeAA && s.preset == Performance);
    Save();
    s.upscaler = UpscalerOff;
    Load();
    assert(s.upscaler == UpscalerTaa && s.preset == Performance);
    assert(RenderPreset() == NativeAA && !ResolutionNeedsRestart());
    s.upscaler = UpscalerFsr3;
    assert(RenderPreset() == Performance);
    for (bool fsr4 : {false, true}) {
        for (bool fsr411 : {false, true}) {
            for (int requested = 0; requested < UpscalerCount; ++requested) {
                FILE* config = std::fopen(path, "w");
                assert(config);
                std::fprintf(config, "upscaler=%s\npreset=3\noutput_res=2560x1440\n",
                             UpscalerName(requested));
                std::fclose(config);
                s.fsr4_problem = nullptr;
                Load();
                assert(s.upscaler == requested);
                ConfigureUpscalerSupport(fsr4, fsr411);
                const bool unsupported = (requested == UpscalerFsr4 && !fsr4) ||
                    (requested == UpscalerFsr411 && !(fsr4 && fsr411));
                // The saved/requested choice is kept; only the active provider falls back.
                assert(s.upscaler == requested);
                assert(s.active_upscaler == (unsupported ? UpscalerFsr3 : requested));
                assert(s.fsr4_supported == fsr4);
                assert(s.fsr411_supported == (fsr4 && fsr411));
                assert(bool(s.fsr4_problem.load()) == unsupported);
                assert(bool(s.upscaler_fallback_reason.load()) == unsupported);
                assert(s.preset == Performance && s.output_res == 2);
                // Startup patch settings still describe the already applied guest patches.
                assert(s.startup_upscaler == requested);
                ConfigureUpscalerSupport(fsr4, fsr411);
                assert(s.upscaler == requested);
                assert(s.active_upscaler == (unsupported ? UpscalerFsr3 : requested));
            }
        }
    }
    // Record-time FSR 4 initialization policy: the menu can select FSR 4 between display
    // passes, after the implementation was released for another provider. RecordFsr4 must
    // create it then, and must not create it for an unsupported/failed provider.
    assert(Fsr4ImplementationNeededForRecord(UpscalerFsr4, true, false, false));
    assert(Fsr4ImplementationNeededForRecord(UpscalerFsr411, true, false, false));
    assert(!Fsr4ImplementationNeededForRecord(UpscalerFsr3, true, false, false));
    assert(!Fsr4ImplementationNeededForRecord(UpscalerFsr4, false, false, false));
    assert(!Fsr4ImplementationNeededForRecord(UpscalerFsr4, true, true, false));
    assert(!Fsr4ImplementationNeededForRecord(UpscalerFsr4, true, false, true));
    {
        // FSR 3 -> FSR 4 -> FSR 3 -> FSR 4 transition, with the implementation released when
        // another provider is active and recreated by the next FSR 4 record.
        bool have_impl = true;
        assert(!Fsr4ImplementationNeededForRecord(UpscalerFsr3, true, false, have_impl));
        have_impl = false;
        assert(Fsr4ImplementationNeededForRecord(UpscalerFsr4, true, false, have_impl));
        have_impl = true; // created by RecordFsr4 before the display pass ran
        assert(!Fsr4ImplementationNeededForRecord(UpscalerFsr4, true, false, have_impl));
        have_impl = false; // leaving FSR 4 released it
        assert(!Fsr4ImplementationNeededForRecord(UpscalerFsr3, true, false, have_impl));
        assert(Fsr4ImplementationNeededForRecord(UpscalerFsr4, true, false, have_impl));
    }
    s.startup_preset = Quality;
    s.startup_upscaler = UpscalerFsr3;
    s.upscaler = UpscalerFsr3;
    s.preset = Performance;
    assert(RenderPreset() == Performance && !ResolutionNeedsRestart());
    setenv("BB_RENDER_RES", "1706x960", 1);
    assert(RenderPreset() == Quality && ResolutionNeedsRestart());
    s.preset = Quality;
    assert(!ResolutionNeedsRestart());
    s.upscaler = UpscalerOff;
    assert(ResolutionNeedsRestart());
    s.upscaler = UpscalerFsr4;
    assert(!ResolutionNeedsRestart()); // provider change at the same patched size is live
    s.upscaler = UpscalerTaa;          // TAA needs native guest targets
    assert(ResolutionNeedsRestart());
    s.upscaler = UpscalerFsr4;
    const int output = s.startup_output_res;
    s.output_res = (output + 1) % OutputCount;
    assert(ResolutionNeedsRestart());
    s.output_res = output;
    setenv("BB_RENDER_RES", "", 1);
    assert(!FixedRenderSession() && !ResolutionNeedsRestart());
    unsetenv("BB_RENDER_RES");
    // A failed optional DLSS device must fall back before rendering and keep the saved
    // choice so fixing CUDA/UVM restores DLSS on the next launch.
    {
        FILE* config = std::fopen(path, "w");
        assert(config);
        std::fputs("upscaler=dlss\npreset=3\noutput_res=2560x1440\n", config);
        std::fclose(config);
        Load();
        ConfigureDlssSupport(false, "Vulkan device creation failed with DLSS extensions");
        // Keep the saved choice; only the provider that runs falls back.
        assert(s.upscaler == UpscalerDlss && !s.dlss_supported);
        assert(s.active_upscaler == UpscalerFsr3);
        assert(s.upscaler_fallback_reason.load());
        assert(s.dlss_problem.load() && s.startup_upscaler == UpscalerDlss);
        assert(s.preset == Performance && s.output_res == 2);
        Load();
        assert(s.upscaler == UpscalerDlss && s.active_upscaler == UpscalerDlss);
        ConfigureDlssSupport(true, nullptr);
        assert(s.upscaler == UpscalerDlss && s.active_upscaler == UpscalerDlss &&
               s.dlss_supported && !s.dlss_problem.load() && !s.upscaler_fallback_reason.load());
    }
    std::remove(path);
    std::puts("Upscaler support: saved choices and FSR 3.1 fallback PASS");
}
