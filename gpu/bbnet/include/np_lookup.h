// SPDX-License-Identifier: GPL-2.0-or-later
// bbport: sceNpLookupNpId on a shadNet server without the LookupOnlineId command. shadnet-p2p
// (Wozzardman's, which BBSC and the launcher's seamless co-op hosts run) answers an unknown
// command with ErrorType::Invalid. On shadNet an NpId is the online id in its handle, so the asked
// id is the answer, as BBSC's BBport build gives it. A guest joining a room that already holds a
// guest looks that guest up; when the lookup failed it left the room, so a third player could not
// stay (#231). Header-only for tests/test_np_lookup.cpp.
#pragma once

#include <cstdint>
#include <optional>
#include <string>

namespace bbnet {

// shadNet's ErrorType::Invalid (shadnet/client.h, shadnet-p2p src/protocol.h).
inline constexpr std::uint8_t kShadNetErrorInvalid = 2;

// The online id to answer with when the server cannot look `asked` up (`error`: the reply's
// ErrorType); nothing when its own answer stands (found, not found, bad input, other errors).
inline std::optional<std::string> LookupWithoutServer(std::uint8_t error, const std::string& asked) {
    if (error != kShadNetErrorInvalid || asked.empty()) return std::nullopt;
    return asked;
}

} // namespace bbnet
