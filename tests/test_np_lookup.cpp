// SPDX-License-Identifier: GPL-2.0-or-later
// sceNpLookupNpId on a shadNet server without LookupOnlineId (gpu/bbnet/include/np_lookup.h, #231):
// that server's Invalid answers with the asked online id; its other answers stand.
#include <cassert>
#include <cstdio>
#include "np_lookup.h"

int main() {
    using bbnet::LookupWithoutServer;
    // shadnet-p2p: "Unknown command" -> ErrorType::Invalid (2).
    assert(LookupWithoutServer(2, "Hunter-2") == std::optional<std::string>("Hunter-2"));
    assert(!LookupWithoutServer(2, ""));
    assert(!LookupWithoutServer(0, "Hunter-2"));   // NoError: the server's own npid
    assert(!LookupWithoutServer(3, "Hunter-2"));   // InvalidInput
    assert(!LookupWithoutServer(26, "Hunter-2"));  // NotFound: no such player
    assert(!LookupWithoutServer(23, "Hunter-2"));  // Unauthorized
    std::puts("np-lookup-test: ok");
    return 0;
}
