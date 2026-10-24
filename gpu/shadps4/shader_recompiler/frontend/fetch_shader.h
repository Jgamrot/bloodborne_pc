// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <array>
#include <cstdlib>
#include <optional>
#include <vector>
#include "common/types.h"
#include "shader_recompiler/info.h"

namespace Serialization {
struct Archive;
}

namespace Shader::Gcn {

struct VertexAttribute {
    enum InstanceIdType : u8 {
        None = 0,
        OverStepRate0 = 1,
        OverStepRate1 = 2,
        Plain = 3,
    };

    u8 semantic;      ///< Semantic index of the attribute
    u8 dest_vgpr;     ///< Destination VGPR to load first component.
    u8 num_elements;  ///< Number of components to load
    u8 sgpr_base;     ///< SGPR that contains the pointer to the list of vertex V#
    u8 dword_offset;  ///< The dword offset of the V# that describes this attribute.
    u8 instance_data; ///< Indicates that the buffer will be accessed in instance rate
    u8 inst_offset;   ///< Instruction offset applied on the formatted buffer loads
    u8 data_format{}; ///< Data format override when typed buffer loads are used
    u8 num_format{};  ///< Number format override when typed buffer loads are used

    InstanceIdType GetStepRate() const {
        return static_cast<InstanceIdType>(instance_data);
    }

    /// The descriptor as the game's memory holds it (bbport: or the pre-build's stored copy).
    AmdGpu::Buffer ReadRawSharp(const Shader::Info& info) const noexcept;

    AmdGpu::Buffer GetSharp(const Shader::Info& info) const noexcept {
        auto buffer = ReadRawSharp(info);
        buffer.base_address += inst_offset;
        if (data_format) {
            buffer.data_format = data_format;
            buffer.num_format = num_format;
        }
        return buffer;
    }

    bool operator==(const VertexAttribute& other) const {
        return semantic == other.semantic && dest_vgpr == other.dest_vgpr &&
               num_elements == other.num_elements && sgpr_base == other.sgpr_base &&
               dword_offset == other.dword_offset && instance_data == other.instance_data;
    }
};

struct FetchShaderData {
    u32 size = 0;
    std::vector<VertexAttribute> attributes;
    s8 vertex_offset_sgpr = -1;   ///< SGPR of vertex offset from VADDR
    s8 instance_offset_sgpr = -1; ///< SGPR of instance offset from VADDR

    bool operator==(const FetchShaderData& other) const {
        return attributes == other.attributes && vertex_offset_sgpr == other.vertex_offset_sgpr &&
               instance_offset_sgpr == other.instance_offset_sgpr;
    }

    void Serialize(Serialization::Archive& ar) const;
    bool Deserialize(Serialization::Archive& buffer);
};

const u32* GetFetchShaderCode(const Info& info, u32 sgpr_base);

std::optional<FetchShaderData> ParseFetchShader(const Shader::Info& info);

/// bbport shader pre-build: translating a cached permutation outside the game, there is no
/// guest memory to read the fetch shader from; the pre-build thread sets the parse the cache
/// stored with the permutation, and ParseFetchShader returns it.
inline thread_local const std::optional<FetchShaderData>* offline_fetch_shader = nullptr;
/// ... and each attribute's vertex buffer descriptor, by semantic (null: none stored).
inline thread_local const std::array<std::optional<AmdGpu::Buffer>, 32>* offline_attrib_sharps =
    nullptr;

inline AmdGpu::Buffer VertexAttribute::ReadRawSharp(const Shader::Info& info) const noexcept {
    if (offline_attrib_sharps && semantic < offline_attrib_sharps->size() &&
        (*offline_attrib_sharps)[semantic]) {
        return *(*offline_attrib_sharps)[semantic];
    }
    return info.ReadUdReg<AmdGpu::Buffer>(sgpr_base, dword_offset);
}

/// bbport: a V# without records reads as zero through a float input (the specialization keeps
/// none of its fields; a zeroed V# was a VK_FORMAT_UNDEFINED attribute). BB_NULL_VERTEX_INPUT=0.
inline bool IsNullVertexInput(const AmdGpu::Buffer& sharp, bool enabled) noexcept {
    return enabled && !sharp;
}

inline bool IsNullVertexInput(const AmdGpu::Buffer& sharp) noexcept {
    static const bool enabled = [] {
        const char* value = std::getenv("BB_NULL_VERTEX_INPUT");
        return !value || value[0] != '0';
    }();
    return IsNullVertexInput(sharp, enabled);
}

struct VertexInputFormat {
    AmdGpu::DataFormat data_format;
    AmdGpu::NumberFormat num_format;
    u32 stride;
};

/// The host vertex input of an attribute: a null one fetches a float4 from no buffer.
inline VertexInputFormat GetVertexInputFormat(const AmdGpu::Buffer& sharp, bool null) noexcept {
    if (null) {
        return {AmdGpu::DataFormat::Format32_32_32_32, AmdGpu::NumberFormat::Float, 0};
    }
    return {sharp.GetDataFmt(), sharp.GetNumberFmt(), sharp.GetStride()};
}

inline VertexInputFormat GetVertexInputFormat(const AmdGpu::Buffer& sharp) noexcept {
    return GetVertexInputFormat(sharp, IsNullVertexInput(sharp));
}

} // namespace Shader::Gcn
