// SPDX-License-Identifier: GPL-2.0-or-later
// Uses the production descriptor reader; no game files, Vulkan device or window needed.
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include "shader_recompiler/frontend/fetch_shader.h"

int main() {
    constexpr u32 pointer_reg = 2;
    constexpr u32 descriptor_offset = 4;
    std::array<u32, Shader::NUM_USER_DATA_REGS> registers{};
    std::array<u32, 8> table{};
    Shader::Info info{};
    info.user_data = registers;

    AmdGpu::Buffer expected{};
    expected.base_address = 0x123400;
    expected.stride = 16;
    expected.num_records = 12;
    std::memcpy(table.data() + descriptor_offset, &expected, sizeof(expected));

    const auto set_pointer = [&](u64 pointer) {
        std::memcpy(registers.data() + pointer_reg, &pointer, sizeof(pointer));
    };
    const auto read = [&] {
        return info.ReadUdReg<AmdGpu::Buffer>(pointer_reg, descriptor_offset);
    };

    // Regression: null table plus a nonzero descriptor offset must not read low memory.
    assert(read() == AmdGpu::Buffer{});
    assert(!read());
    assert(info.UdPointerNull(pointer_reg));
    // Pointer metadata is masked before deciding whether the table is null.
    set_pointer(0xabcd000000000000ULL);
    assert(read() == AmdGpu::Buffer{});
    // A null pointer plus an offset (below 64 KiB) is no table either.
    for (const u64 low : {0x40ULL, 0xfff0ULL, 0xabcd000000000040ULL}) {
        set_pointer(low);
        assert(info.UdPointerNull(pointer_reg));
        assert(read() == AmdGpu::Buffer{});
    }
    set_pointer(0x10000);
    assert(!info.UdPointerNull(pointer_reg));
    assert(!info.UdPointerNull(Shader::IR::NumScalarRegs));
    set_pointer(0);

    // The vertex consumer must still see an empty descriptor with load overrides applied.
    Shader::Gcn::VertexAttribute attribute{};
    attribute.sgpr_base = pointer_reg;
    attribute.dword_offset = descriptor_offset;
    attribute.inst_offset = 8;
    attribute.data_format = static_cast<u8>(AmdGpu::DataFormat::Format32);
    assert(!attribute.GetSharp(info));

    // Valid tables, masked pointer metadata and instruction offsets retain their behavior.
    set_pointer(reinterpret_cast<u64>(table.data()) | 0xabcd000000000000ULL);
    assert(read() == expected);
    const auto vertex = attribute.GetSharp(info);
    assert(vertex.num_records == expected.num_records);
    assert(vertex.base_address == expected.base_address + attribute.inst_offset);
    assert(vertex.data_format == attribute.data_format);

    // A V# copy taken earlier (draw preparation) is stale once the game rewrites the table.
    Shader::Gcn::FetchShaderData fetch{};
    fetch.attributes = {attribute};
    const AmdGpu::Buffer prepared[] = {vertex};
    assert(fetch.SharpsUnchanged(info, prepared));
    auto rewritten = expected;
    rewritten.stride = 32;
    std::memcpy(table.data() + descriptor_offset, &rewritten, sizeof(rewritten));
    assert(!fetch.SharpsUnchanged(info, prepared));
    std::memcpy(table.data() + descriptor_offset, &expected, sizeof(expected));
    assert(fetch.SharpsUnchanged(info, prepared));

    // The direct-register path bypasses the pointer indirection.
    std::memcpy(registers.data() + descriptor_offset, &expected, sizeof(expected));
    assert(info.ReadUdReg<AmdGpu::Buffer>(Shader::IR::NumScalarRegs, descriptor_offset) == expected);

    // Draw snapshots take precedence over current user data, including a null table.
    std::array<u32, Shader::NUM_USER_DATA_REGS> snapshot_registers{};
    Shader::Info::ud_snapshots[0] = {
        &info, snapshot_registers.data(), static_cast<u32>(snapshot_registers.size()),
        nullptr, 0, 0,
    };
    Shader::Info::num_ud_snapshots = 1;
    assert(read() == AmdGpu::Buffer{});
    assert(!attribute.GetSharp(info));
    const auto snapshot_pointer = reinterpret_cast<u64>(table.data());
    std::memcpy(snapshot_registers.data() + pointer_reg, &snapshot_pointer, sizeof(snapshot_pointer));
    assert(read() == expected);
    Shader::Info::num_ud_snapshots = 0;

    // A zeroed V# in a valid table is a null vertex input: a float4 from no buffer, not the
    // FormatInvalid (VK_FORMAT_UNDEFINED) of its own fields.
    using Shader::Gcn::GetVertexInputFormat;
    using Shader::Gcn::IsNullVertexInput;
    std::memset(table.data() + descriptor_offset, 0, sizeof(AmdGpu::Buffer));
    set_pointer(reinterpret_cast<u64>(table.data()));
    attribute.inst_offset = 0;
    attribute.data_format = 0;
    const auto zeroed = attribute.GetSharp(info);
    assert(IsNullVertexInput(zeroed) && IsNullVertexInput(zeroed, true));
    auto input = GetVertexInputFormat(zeroed);
    assert(input.data_format == AmdGpu::DataFormat::Format32_32_32_32);
    assert(input.num_format == AmdGpu::NumberFormat::Float && input.stride == 0);
    input = GetVertexInputFormat(zeroed, false);
    assert(input.data_format == AmdGpu::DataFormat::FormatInvalid);
    assert(!IsNullVertexInput(zeroed, false));

    // No records but leftover fields: the specialization keeps none of them, nor does the input.
    AmdGpu::Buffer leftover{};
    leftover.base_address = 0x5000;
    leftover.stride = 4000;
    leftover.data_format = static_cast<u32>(AmdGpu::DataFormat::Format8_8_8_8);
    leftover.num_format = static_cast<u32>(AmdGpu::NumberFormat::Uint);
    assert(IsNullVertexInput(leftover));
    input = GetVertexInputFormat(leftover);
    assert(input.num_format == AmdGpu::NumberFormat::Float && input.stride == 0);

    // A V# with records keeps its own format and stride.
    std::memcpy(table.data() + descriptor_offset, &expected, sizeof(expected));
    const auto valid = attribute.GetSharp(info);
    assert(!IsNullVertexInput(valid));
    input = GetVertexInputFormat(valid);
    assert(input.data_format == valid.GetDataFmt() && input.stride == expected.stride);
    set_pointer(0);

    std::puts("Shader user data: null and low tables, vertex consumers, stale V# copies, null vertex "
              "inputs, direct registers and snapshots passed");
}
