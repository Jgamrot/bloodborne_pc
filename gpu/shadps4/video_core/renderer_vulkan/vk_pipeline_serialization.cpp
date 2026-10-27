// SPDX-FileCopyrightText: Copyright 2025-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <array>
#include <chrono>
#include <cstdio>
#include <stdexcept>
#include <string>
#include "common/serdes.h"
#include "core/emulator_settings.h"
#include "shader_recompiler/frontend/fetch_shader.h"
#include "shader_recompiler/info.h"
#include "video_core/cache_storage.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
#include "video_core/renderer_vulkan/vk_shader_prebuild.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/shader_build.h"
#include "common/hash.h"

void SetWindowStatus(const std::string& status); // gpu/shim/window.cpp: the title status

namespace Serialization {
/* You should increment versions below once corresponding serialization scheme is changed. */
static constexpr u32 ShaderBinaryVersion = 8u; // bbport: subgroup barriers for shared memory
static constexpr u32 ShaderMetaVersion = 8u; // bbport: pre-build (attribute V#s, tess constants)
static constexpr u32 PipelineKeyVersion = 6u; // bbport: vertex shaders paired by binding start
} // namespace Serialization

namespace Vulkan {


// bbport shader pre-build: permutations the warm-up translated from the game files this start,
// and those it could not (their pipelines compile when first drawn, as before).
static u32 prebuild_translated = 0, prebuild_failed = 0, prebuild_relaid = 0;

// bbport: why the warm-up left a stored pipeline out, counted for its summary.
enum class WarmUpSkip : u8 {
    Motion,
    KeyVersion,
    MissingShader,
    StaleShader,
    NoSpirv,
    BindingStart,
    Conflict,
    Refused,
    Damaged,
    Other,
    Count,
};
static constexpr std::array<const char*, size_t(WarmUpSkip::Count)> WarmUpSkipNames = {
    "motion vectors (built at first use on purpose)",
    "key from another version",
    "missing shader record",
    "shader record from another version",
    "no SPIR-V",
    "binding starts don't match",
    "permutation index conflict",
    "refused by the driver",
    "damaged record",
    "other",
};
static WarmUpSkip warmup_skip = WarmUpSkip::Other;
// Where the stage LoadPipelineStage loaded last starts its bindings, and how many it has.
static Shader::Backend::Bindings stage_start{}, stage_count{};
static u32 built_with_mismatched_starts = 0;

void RegisterPipelineData(const ComputePipelineKey& key,
                          ComputePipeline::SerializationSupport& sdata) {
    if (!Storage::DataBase::Instance().IsOpened()) {
        return;
    }

    Serialization::Archive ar{};
    Serialization::Writer pldata{ar};

    pldata.Write(Serialization::PipelineKeyVersion);
    pldata.Write(u32{1}); // compute

    key.Serialize(ar);
    sdata.Serialize(ar);

    Storage::DataBase::Instance().Save(Storage::BlobType::PipelineKey,
                                       fmt::format("c_{:#018x}", key.value), ar.TakeOff());
}

void RegisterPipelineData(const GraphicsPipelineKey& key, u64 hash,
                          GraphicsPipeline::SerializationSupport& sdata) {
    if (!Storage::DataBase::Instance().IsOpened()) {
        return;
    }

    Serialization::Archive ar{};
    Serialization::Writer pldata{ar};

    pldata.Write(Serialization::PipelineKeyVersion);
    pldata.Write(u32{0}); // graphics

    key.Serialize(ar);
    sdata.Serialize(ar);

    Storage::DataBase::Instance().Save(Storage::BlobType::PipelineKey,
                                       fmt::format("g_{:#018x}", hash), ar.TakeOff());
}

void RegisterShaderMeta(const Shader::Info& info,
                        const std::optional<Shader::Gcn::FetchShaderData>& fetch_shader_data,
                        const Shader::StageSpecialization& spec, size_t perm_hash,
                        size_t perm_idx) {
    if (!Storage::DataBase::Instance().IsOpened()) {
        return;
    }

    Serialization::Archive ar;
    Serialization::Writer meta{ar};

    meta.Write(Serialization::ShaderMetaVersion);
    meta.Write(Serialization::ShaderBinaryVersion);

    meta.Write(perm_hash);
    meta.Write(perm_idx);

    spec.Serialize(ar);
    info.Serialize(ar);

    Storage::DataBase::Instance().Save(Storage::BlobType::ShaderMeta,
                                       fmt::format("{:#018x}", perm_hash), ar.TakeOff());
}

void RegisterShaderBinary(std::vector<u32>&& spv, u64 pgm_hash, size_t perm_idx) {
    if (!Storage::DataBase::Instance().IsOpened()) {
        return;
    }

    Storage::DataBase::Instance().Save(Storage::BlobType::ShaderBinary,
                                       fmt::format("{:#018x}_{}", pgm_hash, perm_idx),
                                       std::move(spv));
}

bool LoadShaderMeta(Serialization::Archive& ar, Shader::Info& info,
                    std::optional<Shader::Gcn::FetchShaderData>& fetch_shader_data,
                    Shader::StageSpecialization& spec, size_t& perm_idx, bool* spirv_current) {
    Serialization::Reader meta{ar};

    u32 meta_version{};
    meta.Read(meta_version);
    if (meta_version != Serialization::ShaderMetaVersion) {
        return false;
    }

    u32 binary_version{};
    meta.Read(binary_version);
    if (spirv_current) {
        *spirv_current = binary_version == Serialization::ShaderBinaryVersion;
    } else if (binary_version != Serialization::ShaderBinaryVersion) {
        return false;
    }

    u64 perm_hash_ar{};
    meta.Read(perm_hash_ar);
    meta.Read(perm_idx);

    spec.Deserialize(ar);
    if (!info.Deserialize(ar)) {
        return false;
    }

    // Motion vertex shaders embed session-local buffer device addresses. They must be
    // recompiled for the current allocation, never loaded from a previous process. bbport
    // shader pre-build: with the game files' code they are translated for this session instead
    // (spirv_current false: their stored SPIR-V is never read, nor their translation stored).
    if (info.hw_stage == Shader::HwStage::Vertex && spec.runtime_info.hw.vs.motion_vectors) {
        if (!spirv_current || Shader::MotionVectors::positions_address == 0) {
            return false;
        }
        *spirv_current = false;
    }

    // bbport: only a stage with a fetch shader sets it: a geometry stage, loaded after the vertex
    // stage, left the pipeline without one.
    if (spec.fetch_shader_data) {
        fetch_shader_data = spec.fetch_shader_data;
    }
    return true;
}

void ComputePipelineKey::Serialize(Serialization::Archive& ar) const {
    Serialization::Writer key{ar};
    key.Write(value);
}

bool ComputePipelineKey::Deserialize(Serialization::Archive& ar) {
    Serialization::Reader key{ar};
    key.Read(value);
    return true;
}

void ComputePipeline::SerializationSupport::Serialize(Serialization::Archive& ar) const {
    // Nothing here yet
    return;
}

bool ComputePipeline::SerializationSupport::Deserialize(Serialization::Archive& ar) {
    // Nothing here yet
    return true;
}

bool PipelineCache::LoadComputePipeline(Serialization::Archive& ar) {
    compute_key.Deserialize(ar);

    ComputePipeline::SerializationSupport sdata{};
    sdata.Deserialize(ar);

    std::vector<u8> meta_blob;
    Storage::DataBase::Instance().Load(Storage::BlobType::ShaderMeta,
                                       fmt::format("{:#018x}", compute_key.value), meta_blob);
    if (meta_blob.empty()) {
        warmup_skip = WarmUpSkip::MissingShader;
        return false;
    }

    Serialization::Archive meta_ar{std::move(meta_blob)};

    if (!LoadPipelineStage(meta_ar, 0)) {
        return false;
    }

    const auto [it, is_new] = compute_pipelines.try_emplace(compute_key);
    ASSERT(is_new);

    it.value() =
        std::make_unique<ComputePipeline>(instance, scheduler, desc_heap, profile, *pipeline_cache,
                                          compute_key, *sel.infos[0], sel.modules[0], sdata, true);

    sel.infos.fill(nullptr);
    sel.modules.fill(nullptr);

    // bbport: a cached pipeline the driver cannot create (a new driver, or one saved by a build
    // that stopped on it) stopped every start here. It is compiled again when the game uses it.
    if (!it.value()->IsValid()) {
        compute_pipelines.erase(compute_key);
        warmup_skip = WarmUpSkip::Refused;
        return false;
    }
    return true;
}

void GraphicsPipelineKey::Serialize(Serialization::Archive& ar) const {
    Serialization::Writer key{ar};

    key.Write(this, sizeof(*this));
}

bool GraphicsPipelineKey::Deserialize(Serialization::Archive& ar) {
    Serialization::Reader key{ar};

    key.Read(this, sizeof(*this));
    return true;
}

void GraphicsPipeline::SerializationSupport::Serialize(Serialization::Archive& ar) const {
    Serialization::Writer sdata{ar};

    sdata.Write(&vertex_attributes, sizeof(vertex_attributes));
    sdata.Write(&vertex_bindings, sizeof(vertex_bindings));
    sdata.Write(&divisors, sizeof(divisors));
    sdata.Write(multisampling);
    sdata.Write(tcs);
    sdata.Write(tes);
    sdata.Write(u8(clip_distances.value_or(false)));
}

bool GraphicsPipeline::SerializationSupport::Deserialize(Serialization::Archive& ar) {
    Serialization::Reader sdata{ar};

    sdata.Read(&vertex_attributes, sizeof(vertex_attributes));
    sdata.Read(&vertex_bindings, sizeof(vertex_bindings));
    sdata.Read(&divisors, sizeof(divisors));
    sdata.Read(multisampling);
    sdata.Read(tcs);
    sdata.Read(tes);
    if (!ar.IsEoS()) { // pipelines saved before it have none
        u8 clip{};
        sdata.Read(clip);
        clip_distances = clip != 0;
    }
    return true;
}

bool PipelineCache::LoadGraphicsPipeline(Serialization::Archive& ar) {
    // bbport: a pipeline that failed to load (a stale stage) returned with the stages it had
    // already loaded still selected, and the next one kept them for the stages it does not have:
    // a shadow pipeline (no fragment shader) was built with another pipeline's fragment shader,
    // and cast striped shadows (Chalice Dungeons, NVIDIA, a cache with stale entries).
    sel.infos.fill(nullptr);
    sel.modules.fill(nullptr);
    sel.fetch_shader.reset();
    sel.graphics_key.Deserialize(ar);

    // bbport: motion-vector pipelines are never preloaded. Their vertex shader embeds session-
    // local buffer addresses (see LoadShaderMeta), and the shader metadata is stored once per
    // program, not per permutation: the meta found for a motion pipeline's stages could be the
    // plain permutation, so LoadShaderMeta's motion check missed it and the preload built the
    // 8-attachment motion key with plain shaders. The AMD driver refused some of these
    // (ErrorUnknown: the startup crash), and the ones it accepted were registered under the
    // motion key without motion output. Built at first use instead, like the vertex shaders.
    if (sel.graphics_key.motion_vectors) {
        warmup_skip = WarmUpSkip::Motion;
        return false;
    }

    GraphicsPipeline::SerializationSupport sdata{};
    sdata.Deserialize(ar);

    // bbport: without a pixel shader, clip distance emulation's discard shader follows the
    // draw's registers as saved; a pipeline saved without them is compiled when first drawn.
    if (!sel.graphics_key.stage_hashes[u32(Shader::SwStage::Fragment)]) {
        if (!sdata.clip_distances && profile.needs_clip_distance_emulation) {
            return false;
        }
        auto& fs = sel.runtime_infos[u32(Shader::SwStage::Fragment)];
        fs.Initialize(Shader::HwStage::Fragment, Shader::SwStage::Fragment);
        fs.hw.fs.clip_distance_emulation =
            sdata.clip_distances.value_or(false) && profile.needs_clip_distance_emulation;
    }

    // Diagnosis only: each stage's bindings should start where the stages before it end
    // (fragment first, as RefreshGraphicsStages binds them).
    Shader::Backend::Bindings expected{};
    bool starts_differ = false;
    for (int stage_idx = 0; stage_idx < MaxShaderStages; ++stage_idx) {
        const auto& hash = sel.graphics_key.stage_hashes[stage_idx];
        if (!hash) {
            continue;
        }

        std::vector<u8> meta_blob;
        Storage::DataBase::Instance().Load(Storage::BlobType::ShaderMeta,
                                           fmt::format("{:#018x}", hash), meta_blob);
        if (meta_blob.empty()) {
            warmup_skip = WarmUpSkip::MissingShader;
            return false;
        }

        Serialization::Archive meta_ar{std::move(meta_blob)};

        if (!LoadPipelineStage(meta_ar, stage_idx)) {
            return false;
        }
        starts_differ |= stage_start.unified != expected.unified ||
                         stage_start.buffer != expected.buffer;
        expected.unified += stage_count.unified;
        expected.buffer += stage_count.buffer;
    }

    const auto [it, is_new] = graphics_pipelines.try_emplace(sel.graphics_key);
    ASSERT(is_new);

    it.value() = std::make_unique<GraphicsPipeline>(
        instance, scheduler, desc_heap, profile, sel.graphics_key, *pipeline_cache, sel.infos,
        sel.runtime_infos, sel.fetch_shader, sel.modules, sdata, true);

    sel.infos.fill(nullptr);
    sel.modules.fill(nullptr);
    sel.fetch_shader.reset();

    // bbport: as for compute pipelines, a failed one is left to compile when the game uses it.
    if (!it.value()->IsValid()) {
        graphics_pipelines.erase(sel.graphics_key);
        warmup_skip = starts_differ ? WarmUpSkip::BindingStart : WarmUpSkip::Refused;
        return false;
    }
    built_with_mismatched_starts += starts_differ;
    return true;
}

bool PipelineCache::LoadPipelineStage(Serialization::Archive& ar, size_t stage) {
    auto program = std::make_unique<Program>();
    Shader::StageSpecialization spec{};
    spec.info = &program->info;
    size_t perm_idx{};
    // bbport shader pre-build: with the game files' code available, a permutation whose SPIR-V
    // is missing or from another translator version is translated again instead of dropped.
    bool spirv_current = true;
    if (!LoadShaderMeta(ar, program->info, sel.fetch_shader, spec, perm_idx,
                        Prebuild::Available() ? &spirv_current : nullptr)) {
        warmup_skip = program->info.hw_stage == Shader::HwStage::Vertex &&
                              spec.runtime_info.hw.vs.motion_vectors
                          ? WarmUpSkip::Motion
                          : WarmUpSkip::StaleShader;
        return false;
    }

    // Permutation hash depends on shader variation index. To prevent collisions, we need insert it
    // at the exact position rather than append

    vk::ShaderModule module{};
    // Most pipeline keys reuse a shader module already loaded during warmup. Avoid
    // opening and allocating its SPIR-V binary again for every repeated stage.
    const auto compile = [&] {
        std::vector<u32> spv;
        const auto spv_name = fmt::format("{:#018x}_{}", program->info.pgm_hash, perm_idx);
        if (spirv_current &&
            (!Prebuild::Available() ||
             Storage::DataBase::Instance().Has(Storage::BlobType::ShaderBinary, spv_name))) {
            Storage::DataBase::Instance().Load(Storage::BlobType::ShaderBinary, spv_name, spv);
        }
        if (spv.empty() && Prebuild::Available()) {
            Shader::Info translated{};
            spv = Prebuild::Translate(program->info, sel.fetch_shader, spec, perm_idx, profile,
                                      &translated);
            if (spv.empty()) {
                ++prebuild_failed;
                return vk::ShaderModule{};
            }
            ++prebuild_translated;
            // A record from another system (the shipped catalog) may lay the resources out
            // differently from this GPU's translation: then the pipeline binds them as
            // translated here. Otherwise the stored layout stays - replacing it with an equal
            // one made the game's permutation lookup miss (45 recompiles at world load).
            const auto& stored = program->info;
            const bool same_layout = translated.buffers.size() == stored.buffers.size() &&
                                     translated.images.size() == stored.images.size() &&
                                     translated.samplers.size() == stored.samplers.size() &&
                                     translated.fmasks.size() == stored.fmasks.size() &&
                                     translated.ud_mask.mask == stored.ud_mask.mask;
            if (!same_layout) {
                ++prebuild_relaid;
                translated.user_data = program->info.user_data;
                program->info = std::move(translated);
            }
            const bool session_local = program->info.hw_stage == Shader::HwStage::Vertex &&
                                       spec.runtime_info.hw.vs.motion_vectors;
            if (!session_local) {
                RegisterShaderBinary(std::vector<u32>(spv), program->info.pgm_hash, perm_idx);
            }
            if (!session_local && (!spirv_current || !same_layout)) { // layout, SPIR-V version
                RegisterShaderMeta(program->info, sel.fetch_shader, spec,
                                   HashCombine(program->info.pgm_hash, perm_idx), perm_idx);
            }
        }
        if (spv.size() < 5 || spv[0] != 0x07230203u) {
            if (!spv.empty())
                throw std::runtime_error{"damaged SPIR-V in the shader cache"};
            return vk::ShaderModule{};
        }
        auto [result, created] = instance.GetDevice().createShaderModule(
            {.codeSize = spv.size() * sizeof(u32), .pCode = spv.data()});
        if (result != vk::Result::eSuccess)
            throw std::runtime_error{"cached SPIR-V rejected by the driver"};
        return created;
    };

    auto it_pgm = program_cache.find(program->info.pgm_hash);
    warmup_skip = WarmUpSkip::NoSpirv;
    if (it_pgm == program_cache.end()) {
        module = compile();
        if (!module) return false;
        const auto hash = program->info.pgm_hash;
        it_pgm = program_cache.try_emplace(hash, std::move(program)).first;
    } else {
        const auto& it = std::ranges::find(it_pgm.value()->modules, spec, &Program::Module::spec);
        if (it != it_pgm.value()->modules.end()) {
            // A matching permutation is valid only at its original index. A different index means
            // the store holds entries from more than one cache generation, so this pipeline is
            // left to compile at runtime.
            const auto idx = std::distance(it_pgm.value()->modules.begin(), it);
            if (perm_idx != idx) {
                LOG_WARNING(Render_Vulkan,
                            "Cached permutation {} of {}_{:x} conflicts with index {}, skipping "
                            "preload",
                            perm_idx, program->info.hw_stage, program->info.pgm_hash, idx);
                // Equal but for the start, which is not compared without guest resources.
                warmup_skip =
                    it->spec.start != spec.start ? WarmUpSkip::BindingStart : WarmUpSkip::Conflict;
                return false;
            }
            module = it->module;
        } else {
            module = compile();
            if (!module) return false;
        }
    }
    stage_start = spec.start;
    stage_count = {};
    (program ? program->info : it_pgm.value()->info).AddBindings(stage_count);
    spec.info = &it_pgm.value()->info;
    sel.runtime_infos[stage] = spec.runtime_info;
    it_pgm.value()->InsertPermut(module, std::move(spec), perm_idx);

    sel.infos[stage] = &it_pgm.value()->info;
    sel.modules[stage] = module;

    return true;
}

void PipelineCache::WarmUp() {
    if (!EmulatorSettings.IsPipelineCacheEnabled()) {
        return;
    }

    Storage::DataBase::Instance().Open();
    const auto warmup_start = std::chrono::steady_clock::now();
    // bbport shader pre-build: with the game files' code (BB_SHADER_CODE), the cache's records of
    // what the draws saw (and a shipped catalog run.py adds to them) are enough: their SPIR-V is
    // translated here, before the game needs it.
    const bool prebuild = Prebuild::Available();
    if (const char* catalog = std::getenv("BB_SHADER_CATALOG"); prebuild && catalog && *catalog) {
        if (const u32 added = Storage::DataBase::Instance().Seed(catalog)) {
            std::printf("Shader pre-build: %u shader and pipeline records added from the catalog\n",
                        added);
        }
    }

    // bbport: the shader build that wrote the cache (gpu/CMakeLists.txt). The versions above are
    // raised by hand, and a change they missed loaded another build's shaders (dark pictures).
    static const bool check_build = [] {
        const char* value = std::getenv("BB_SHADER_BUILD_CHECK");
        return !value || value[0] != '0';
    }();
    const std::string_view build{BB_SHADER_BUILD};
    const auto save_profile = [&] {
        std::vector<u8> data(sizeof(profile));
        std::memcpy(data.data(), &profile, sizeof(profile));
        Storage::DataBase::Instance().Save(Storage::BlobType::ShaderProfile, "profile",
                                           std::move(data));
        Storage::DataBase::Instance().Save(Storage::BlobType::ShaderProfile, "build",
                                           std::vector<u8>(build.begin(), build.end()));
    };

    // Check if cache is compatible
    std::vector<u8> profile_data{};
    Storage::DataBase::Instance().Load(Storage::BlobType::ShaderProfile, "profile", profile_data);
    std::vector<u8> build_data{};
    Storage::DataBase::Instance().Load(Storage::BlobType::ShaderProfile, "build", build_data);
    const std::string cached_build(build_data.begin(), build_data.end());
    if (profile_data.empty()) {
        Storage::DataBase::Instance().FinishPreload();
        save_profile();
        if (!prebuild) {
            return;
        }
    }
    if (profile_data.size() != sizeof(Shader::Profile)) {
        LOG_WARNING(Render, "Pipeline cache profile has unexpected size ({} != {})",
                    profile_data.size(), sizeof(Shader::Profile));
    }
    Shader::Profile cached_profile{};
    if (profile_data.size() == sizeof(Shader::Profile)) {
        std::memcpy(&cached_profile, profile_data.data(), sizeof(cached_profile));
    }
    const bool other_system = !profile_data.empty() &&
                              (profile_data.size() != sizeof(Shader::Profile) ||
                               cached_profile != profile);
    const bool other_build = !profile_data.empty() && check_build && cached_build != build;
    if (other_build) {
        std::printf("Pipeline cache: written by %s, not this one (shader build %s)\n",
                    cached_build.empty() ? "an earlier build"
                                         : ("shader build " + cached_build.substr(0, 32)).c_str(),
                    BB_SHADER_BUILD);
    }
    if (prebuild && (other_system || other_build)) {
        // bbport shader pre-build: another GPU, driver features or build: only the SPIR-V is
        // stale. Keep what the draws saw and translate it again for this system below.
        std::printf("Shader pre-build: the cache was made for another %s; its shaders are "
                    "translated again from the game files\n",
                    other_system ? "system" : "build");
        Storage::DataBase::Instance().ClearType(Storage::BlobType::ShaderBinary);
        Storage::DataBase::Instance().FinishPreload();
        save_profile();
    } else if (other_system || other_build) {
        // bbport: upstream closed the cache for the session here, so it was never rewritten
        // and every later session compiled every shader again (stutters on each new area).
        // Start a fresh cache for this build and GPU instead.
        LOG_WARNING(Render, "Pipeline cache isn't compatible with current {}: rebuilding it",
                    other_system ? "system" : "build");
        Storage::DataBase::Instance().Clear();
        Storage::DataBase::Instance().FinishPreload();
        save_profile();
        return;
    }

    u32 num_pipelines{};
    u32 num_total_pipelines{};
    std::array<u32, size_t(WarmUpSkip::Count)> skipped{};
    // Progress in the window title while the game waits (a first start with a full catalog
    // builds thousands of pipelines).
    const u32 work = Storage::DataBase::Instance().Count(Storage::BlobType::PipelineKey) +
                     Storage::DataBase::Instance().Count(Storage::BlobType::ShaderMeta);
    u32 done = 0;
    auto shown = std::chrono::steady_clock::now();
    const auto progress = [&] {
        ++done;
        const auto now = std::chrono::steady_clock::now();
        if (work > 200 && now - shown > std::chrono::milliseconds(200)) {
            shown = now;
            SetWindowStatus(fmt::format("Preparing shaders: {}%", std::min(99u, done * 100 / work)));
        }
    };

    Storage::DataBase::Instance().ForEachBlob(
        Storage::BlobType::PipelineKey, [&](std::vector<u8>&& data) {
            ++num_total_pipelines;
            progress();

            Serialization::Archive ar{std::move(data)};
            Serialization::Reader pldata{ar};

            // bbport: a damaged key or shader record (Serialization::CorruptData) is skipped
            // like a stale one; the pipeline is compiled again when the game uses it.
            try {
                u32 version{};
                pldata.Read(version);
                if (version != Serialization::PipelineKeyVersion) {
                    ++skipped[size_t(WarmUpSkip::KeyVersion)];
                    return;
                }

                u32 is_compute{};
                pldata.Read(is_compute);

                bool result{};
                warmup_skip = WarmUpSkip::Other;
                if (is_compute) {
                    result = LoadComputePipeline(ar);
                } else {
                    result = LoadGraphicsPipeline(ar);
                }

                if (result) {
                    ++num_pipelines;
                } else {
                    ++skipped[size_t(warmup_skip)];
                }
            } catch (const std::exception&) {
                ++skipped[size_t(WarmUpSkip::Damaged)];
                sel.infos.fill(nullptr);
                sel.modules.fill(nullptr);
                sel.fetch_shader.reset();
            }
        });

    LOG_INFO(Render, "Preloaded {} pipelines (shader build {})", num_pipelines, build);

    // bbport: shader permutations no stored pipeline uses. A draw that may write object motion
    // first compiles its plain permutation, then the motion one its pipeline actually uses:
    // the plain one is stored but never referenced by a pipeline key, so it was compiled again
    // every session the first time each animated model appeared. Load every stored
    // permutation (modules only; pipelines still come from keys).
    u32 variants = 0;
    Storage::DataBase::Instance().ForEachBlob(
        Storage::BlobType::ShaderMeta, [&](std::vector<u8>&& data) {
            progress();
            Serialization::Archive ar{std::move(data)};
            try {
                variants += LoadPipelineStage(ar, 0);
            } catch (const std::exception&) {
            }
            sel.infos.fill(nullptr);
            sel.modules.fill(nullptr);
            sel.fetch_shader.reset();
        });
    SetWindowStatus({});
    if (prebuild) {
        std::printf("Shader pre-build: %u stored shader variants ready, pipelines or not\n",
                    variants);
        std::printf("Shader pre-build: %u pipelines ready (%u shaders translated from the game "
                    "files, %u could not be, %u laid out anew for this GPU) in %.1f s\n",
                    num_pipelines, prebuild_translated, prebuild_failed, prebuild_relaid,
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - warmup_start)
                        .count());
    }
    if (num_total_pipelines > num_pipelines || built_with_mismatched_starts) {
        std::string reasons;
        for (size_t i = 0; i < skipped.size(); ++i) {
            if (skipped[i]) {
                reasons += fmt::format("{}{} {}", reasons.empty() ? "" : ", ", skipped[i],
                                       WarmUpSkipNames[i]);
            }
        }
        LOG_WARNING(Render,
                    "{} stale pipelines were found ({}; {} built with binding starts that don't "
                    "match). Consider re-generating the cache",
                    num_total_pipelines - num_pipelines, reasons.empty() ? "none" : reasons,
                    built_with_mismatched_starts);
    }

    Storage::DataBase::Instance().FinishPreload();
}

void PipelineCache::Sync() {
    Storage::DataBase::Instance().Close();
}

} // namespace Vulkan

namespace Shader {

void Info::Serialize(Serialization::Archive& ar) const {
    Serialization::Writer info{ar};

    info.Write(this, sizeof(InfoPersistent));
    info.Write(flattened_ud_buf);
    srt_info.Serialize(ar);
}

bool Info::Deserialize(Serialization::Archive& ar) {
    Serialization::Reader info{ar};

    info.Read(this, sizeof(Shader::InfoPersistent));
    info.Read(flattened_ud_buf);

    return srt_info.Deserialize(ar);
}

void Gcn::FetchShaderData::Serialize(Serialization::Archive& ar) const {
    Serialization::Writer fetch{ar};
    ar.Grow(6 + attributes.size() * sizeof(VertexAttribute));

    fetch.Write(size);
    fetch.Write(vertex_offset_sgpr);
    fetch.Write(instance_offset_sgpr);
    fetch.Write(attributes);
}

bool Gcn::FetchShaderData::Deserialize(Serialization::Archive& ar) {
    Serialization::Reader fetch{ar};

    fetch.Read(size);
    fetch.Read(vertex_offset_sgpr);
    fetch.Read(instance_offset_sgpr);
    fetch.Read(attributes);

    return true;
}

void PersistentSrtInfo::Serialize(Serialization::Archive& ar) const {
    Serialization::Writer srt{ar};

    srt.Write(this, sizeof(*this));
    if (walker_func_size) {
        srt.Write(reinterpret_cast<void*>(walker_func), walker_func_size);
    }
}

bool PersistentSrtInfo::Deserialize(Serialization::Archive& ar) {
    Serialization::Reader srt{ar};

    srt.Read(this, sizeof(*this));

    if (walker_func_size) {
        // A size from a damaged record: never look at bytes past its end.
        if (walker_func_size > ar.Remaining()) {
            walker_func = nullptr;
            throw Serialization::CorruptData{};
        }
        // bbport: a walker the old fault handler patched to read 0: the shader is translated
        // again instead, so its draws get their real resource tables back (issue #47).
        const u8* code = ar.CurrPtr();
        if (WalkerCodeLooksPatched({code, walker_func_size})) {
            walker_func = nullptr;
            ar.Advance(walker_func_size);
            return false;
        }
        walker_func = RegisterWalkerCode(code, walker_func_size);
        ar.Advance(walker_func_size);
    }

    return true;
}

void StageSpecialization::Serialize(Serialization::Archive& ar) const {
    Serialization::Writer spec{ar};

    spec.Write(start);
    spec.Write(runtime_info);

    spec.Write(bitset.to_string());

    if (fetch_shader_data) {
        spec.Write(sizeof(*fetch_shader_data));
        fetch_shader_data->Serialize(ar);
    } else {
        spec.Write(size_t{0});
    }

    spec.Write(vs_attribs);
    spec.Write(buffers);
    spec.Write(images);
    spec.Write(fmasks);
    spec.Write(samplers);
    spec.Write(vs_attrib_sharps);
    spec.Write(u8(tess_constants.has_value()));
    if (tess_constants) {
        spec.Write(&*tess_constants, sizeof(*tess_constants));
    }
}

bool StageSpecialization::Deserialize(Serialization::Archive& ar) {
    Serialization::Reader spec{ar};

    spec.Read(start);
    spec.Read(runtime_info);

    std::string bits{};
    spec.Read(bits);
    bitset = std::bitset<MaxStageResources>(bits);

    u64 fetch_data_size{};
    spec.Read(fetch_data_size);

    if (fetch_data_size) {
        Gcn::FetchShaderData fetch_data;
        fetch_data.Deserialize(ar);
        fetch_shader_data = fetch_data;
    }

    spec.Read(vs_attribs);
    spec.Read(buffers);
    spec.Read(images);
    spec.Read(fmasks);
    spec.Read(samplers);
    spec.Read(vs_attrib_sharps);
    u8 has_tess{};
    spec.Read(has_tess);
    if (has_tess) {
        TessellationDataConstantBuffer constants{};
        spec.Read(&constants, sizeof(constants));
        tess_constants = constants;
    }

    return true;
}

} // namespace Shader
