// SPDX-License-Identifier: GPL-2.0-or-later
// GCN NaN/Inf rules in the shader recompiler (Profile::gcn_nan_semantics, BB_GCN_NAN): small pixel
// shaders in GCN code are translated with the rules on and off, and the SPIR-V is checked for the
// instructions each rule needs. No GPU. With a folder argument the SPIR-V is written there (for
// spirv-val).
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <vector>
#include <spirv/unified1/GLSL.std.450.h>
#include <spirv/unified1/spirv.hpp>
#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/info.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/recompiler.h"
#include "shader_recompiler/runtime_info.h"

namespace {

int failures = 0;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            std::fprintf(stderr, "%s: %s failed (line %d)\n", name, #cond, __LINE__);              \
            ++failures;                                                                            \
        }                                                                                          \
    } while (0)

// Encodings (Sea Islands ISA). Sources: 256 + n is vN, 128 is the inline constant 0.
constexpr u32 V(u32 n) {
    return 256 + n;
}
constexpr u32 Vop1(u32 op, u32 vdst, u32 src0) {
    return (0x3Fu << 25) | (vdst << 17) | (op << 9) | src0;
}
constexpr u32 Vop2(u32 op, u32 vdst, u32 src0, u32 vsrc1) {
    return (op << 25) | (vdst << 17) | (vsrc1 << 9) | src0;
}
constexpr u32 Vopc(u32 op, u32 src0, u32 vsrc1) {
    return (0x3Eu << 25) | (op << 17) | (vsrc1 << 9) | src0;
}
std::vector<u32> Vop3(u32 op, u32 vdst, u32 src0, u32 src1, u32 src2, bool clamp = false) {
    return {(0x34u << 26) | (op << 17) | (u32(clamp) << 11) | vdst,
            (src2 << 18) | (src1 << 9) | src0};
}

// s_mov_b32 vcc_hi, 0 / body / exp mrt0 v4, v4, v4, v4 done vm / s_endpgm
std::vector<u32> Program(std::vector<u32> body) {
    std::vector<u32> code{0xBEEB03FFu, 0u};
    code.insert(code.end(), body.begin(), body.end());
    code.push_back((0x3Eu << 26) | (1u << 12) | (1u << 11) | 0xFu);
    code.push_back(0x04040404u);
    code.push_back(0xBF810000u);
    return code;
}

struct Counts {
    std::map<u32, u32> ops;   // core opcodes
    std::map<u32, u32> glsl;  // GLSL.std.450 instructions
    u32 trinary_amd{};        // SPV_AMD_shader_trinary_minmax instructions
    u32 Op(spv::Op op) const {
        const auto it = ops.find(u32(op));
        return it == ops.end() ? 0 : it->second;
    }
    u32 Glsl(u32 inst) const {
        const auto it = glsl.find(inst);
        return it == glsl.end() ? 0 : it->second;
    }
};

Counts Count(const std::vector<u32>& spv) {
    Counts counts;
    u32 glsl_set = ~0u, amd_set = ~0u;
    for (size_t i = 5; i < spv.size();) {
        const u32 words = spv[i] >> 16, op = spv[i] & 0xFFFF;
        if (words == 0) {
            break;
        }
        if (op == u32(spv::Op::OpExtInstImport)) {
            const std::string set{reinterpret_cast<const char*>(&spv[i + 2])};
            (set == "GLSL.std.450" ? glsl_set : amd_set) = spv[i + 1];
        } else if (op == u32(spv::Op::OpExtInst)) {
            if (spv[i + 3] == glsl_set) {
                ++counts.glsl[spv[i + 4]];
            } else if (spv[i + 3] == amd_set) {
                ++counts.trinary_amd;
            }
        }
        ++counts.ops[op];
        i += words;
    }
    return counts;
}

std::filesystem::path out_dir;

Counts Translate(const char* name, const std::vector<u32>& code, bool gcn_nan, bool trinary) {
    using namespace Shader;
    Info info{};
    info.hw_stage = HwStage::Fragment;
    info.sw_stage = SwStage::Fragment;
    RuntimeInfo runtime{};
    runtime.Initialize(info.hw_stage, info.sw_stage);
    auto& fs = runtime.hw.fs;
    // v0..v3: FragCoord x, y, z and 1/w, values the passes cannot fold.
    fs.addr_flags.pos_x_float_ena = 1;
    fs.addr_flags.pos_y_float_ena = 1;
    fs.addr_flags.pos_z_float_ena = 1;
    fs.addr_flags.pos_w_float_ena = 1;
    fs.en_flags = fs.addr_flags;
    fs.color_buffers[0].data_format = AmdGpu::DataFormat::Format32_32_32_32;
    fs.color_buffers[0].num_format = AmdGpu::NumberFormat::Float;
    fs.color_buffers[0].export_format = AmdGpu::ShaderExportFormat::ABGR_32;
    fs.color_buffers[0].swizzle = AmdGpu::IdentityMapping;
    Profile profile{};
    profile.supported_spirv = 0x00010600;
    profile.support_int64 = true;
    profile.support_float64 = true;
    profile.supports_trinary_minmax = trinary;
    profile.gcn_nan_semantics = gcn_nan;
    Pools pools;
    auto program = TranslateProgram(code, pools, info, runtime, profile);
    Backend::Bindings bindings{};
    const auto spv = Backend::SPIRV::EmitSPIRV(profile, runtime, program, bindings);
    if (!out_dir.empty()) {
        std::ofstream out(out_dir / (std::string(name) + (gcn_nan ? "-gcn" : "-old") + ".spv"),
                          std::ios::binary);
        out.write(reinterpret_cast<const char*>(spv.data()), spv.size() * sizeof(u32));
    }
    return Count(spv);
}

void Compare(const char* name, const std::vector<u32>& body, bool trinary, auto&& check) {
    const auto code = Program(body);
    check(name, Translate(name, code, true, trinary), Translate(name, code, false, trinary));
}

} // namespace

int main(int argc, char** argv) {
    if (argc > 1) {
        out_dir = argv[1];
        std::filesystem::create_directories(out_dir);
    }
    // V_MAX_F32 / V_MIN_F32: the non-NaN operand (NMax / NMin).
    Compare("max", {Vop2(16, 4, V(0), 1)}, false, [](const char* name, auto on, auto off) {
        CHECK(on.Glsl(GLSLstd450NMax) == 1 && on.Glsl(GLSLstd450FMax) == 0);
        CHECK(off.Glsl(GLSLstd450NMax) == 0 && off.Glsl(GLSLstd450FMax) == 1);
    });
    Compare("min", {Vop2(15, 4, V(0), 1)}, false, [](const char* name, auto on, auto off) {
        CHECK(on.Glsl(GLSLstd450NMin) == 1 && on.Glsl(GLSLstd450FMin) == 0);
        CHECK(off.Glsl(GLSLstd450NMin) == 0 && off.Glsl(GLSLstd450FMin) == 1);
    });
    // V_MAX_LEGACY_F32 keeps its own NaN select (src1) either way.
    Compare("max-legacy", {Vop2(14, 4, V(0), 1)}, false, [](const char* name, auto on, auto off) {
        CHECK(on.Op(spv::Op::OpIsNan) == 2 && off.Op(spv::Op::OpIsNan) == 2);
    });
    // V_MAX3_F32 / V_MIN3_F32: NMax / NMin chains, also where the AMD trinary ops exist.
    Compare("max3-amd", Vop3(340, 4, V(0), V(1), V(2)), true,
            [](const char* name, auto on, auto off) {
                CHECK(on.Glsl(GLSLstd450NMax) == 2 && on.trinary_amd == 0);
                CHECK(off.Glsl(GLSLstd450NMax) == 0 && off.trinary_amd == 1);
            });
    Compare("min3", Vop3(337, 4, V(0), V(1), V(2)), false,
            [](const char* name, auto on, auto off) {
                CHECK(on.Glsl(GLSLstd450NMin) == 2 && on.Glsl(GLSLstd450FMin) == 0);
                CHECK(off.Glsl(GLSLstd450NMin) == 0 && off.Glsl(GLSLstd450FMin) == 2);
            });
    // V_MED3_F32: MIN3 of the inputs when any is NaN. Selects are counted against the old
    // translation, as the prologue's FragCoord scaling has its own.
    Compare("med3", Vop3(343, 4, V(0), V(1), V(2)), false,
            [](const char* name, auto on, auto off) {
                CHECK(on.Op(spv::Op::OpIsNan) == 3);
                CHECK(on.Op(spv::Op::OpSelect) == off.Op(spv::Op::OpSelect) + 1);
                CHECK(on.Glsl(GLSLstd450NMin) == 2);
                CHECK(off.Op(spv::Op::OpIsNan) == 0 && off.Glsl(GLSLstd450NMin) == 0);
            });
    // The clamp output modifier: NaN becomes 0.
    Compare("clamp", Vop3(259, 4, V(0), V(1), 0, true), false,
            [](const char* name, auto on, auto off) {
                CHECK(on.Glsl(GLSLstd450FClamp) == 0);
                CHECK(on.Glsl(GLSLstd450NMax) == 1 && on.Glsl(GLSLstd450NMin) == 1);
                CHECK(off.Glsl(GLSLstd450FClamp) == 1);
            });
    // V_MAD_LEGACY_F32 / V_MAC_LEGACY_F32: 0 * anything is 0.
    const auto legacy = [](const char* name, auto on, auto off) {
        CHECK(on.Op(spv::Op::OpFOrdEqual) == 2);
        CHECK(on.Op(spv::Op::OpSelect) == off.Op(spv::Op::OpSelect) + 1);
        CHECK(off.Op(spv::Op::OpFOrdEqual) == 0);
    };
    Compare("mad-legacy", Vop3(320, 4, V(0), V(1), V(2)), false, legacy);
    Compare("mac-legacy", {Vop1(1, 4, V(2)), Vop2(6, 4, V(0), 1)}, false, legacy);
    // V_RSQ_CLAMP_F32: +-Inf becomes +-FLT_MAX.
    Compare("rsq-clamp", {Vop1(44, 4, V(0))}, false, [](const char* name, auto on, auto off) {
        CHECK(on.Op(spv::Op::OpIsInf) == 1 && off.Op(spv::Op::OpIsInf) == 0);
        CHECK(on.Op(spv::Op::OpSelect) == off.Op(spv::Op::OpSelect) + 2);
    });
    // V_MUL_LEGACY_F32 already had the rule.
    Compare("mul-legacy", {Vop2(7, 4, V(0), 1)}, false, [](const char* name, auto on, auto off) {
        CHECK(on.Op(spv::Op::OpFOrdEqual) == 2 && off.Op(spv::Op::OpFOrdEqual) == 2);
    });
    // V_CMP_NGE_F32 = !(a >= b): true for NaN, so an unordered less-than. v4 = vcc ? v3 : 0.
    Compare("cmp-nge", {Vopc(9, V(0), 1), Vop2(0, 4, 128, 3)}, false,
            [](const char* name, auto on, auto off) {
                CHECK(on.Op(spv::Op::OpFUnordLessThan) == 1);
                CHECK(on.Op(spv::Op::OpFOrdLessThan) == 0);
                CHECK(off.Op(spv::Op::OpFUnordLessThan) == 0);
                CHECK(off.Op(spv::Op::OpFOrdLessThan) == 1);
            });
    Compare("cmp-neq", {Vopc(13, V(0), 1), Vop2(0, 4, 128, 3)}, false,
            [](const char* name, auto on, auto off) {
                CHECK(on.Op(spv::Op::OpFUnordNotEqual) == 1);
                CHECK(off.Op(spv::Op::OpFOrdNotEqual) == 1);
            });
    Compare("cmp-nlg", {Vopc(10, V(0), 1), Vop2(0, 4, 128, 3)}, false,
            [](const char* name, auto on, auto off) {
                CHECK(on.Op(spv::Op::OpFUnordEqual) == 1 && off.Op(spv::Op::OpFOrdEqual) == 1);
            });
    // Ordered compares stay ordered.
    Compare("cmp-lt", {Vopc(1, V(0), 1), Vop2(0, 4, 128, 3)}, false,
            [](const char* name, auto on, auto off) {
                CHECK(on.Op(spv::Op::OpFOrdLessThan) == 1);
                CHECK(off.Op(spv::Op::OpFOrdLessThan) == 1);
                CHECK(on.Op(spv::Op::OpFUnordLessThan) == 0);
            });
    if (failures) {
        std::fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    std::puts("gcn-nan-test: ok");
    return 0;
}
