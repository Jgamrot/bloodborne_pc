# The Hunter's Dream backend

`thd/` is the online backend for The Hunter's Dream (`online_pool=huntersdream` in the launcher,
which sets `BB_NET_BACKEND=thd`). It is Awaken's adaptation (Awakenchan/BloodBorneButPc,
online-shadps4-0.20) of droogie/bbhost's network side
(https://github.com/droogie/bbhost/tree/566184a74f071166299bb656c4af479e5bbe2771):
`src/hle/net.cpp`, `src/hle/np_matching2.cpp`, `src/hle/np_signaling.cpp`, the NP parts of
`src/hle/system.cpp`, and `src/net/{http,account,session,stun}.cpp`, as Supermedo took it into
Supermedo/bloodborne_pc (3405c4d). These portions are GPL-3.0-or-later
(`packaging/windows/licenses/GPL-3.0-bbhost-online-code.txt`); copyright remains with the bbhost
contributors.

With that pool the game's NP and sceNet imports are these instead of the shadNet ones. sceHttp
stays shadPS4's (`vendor/shadps4/core/libraries/network/http.cpp`), with two `bbport` hooks that act
only in that pool: `*.example.com` host-override keys and the account token and ruleset headers.
The servers see the build as `BB_CLIENT_VERSION` (`yharnam-pc <version>`, set by the
launcher).

The network, NP and shadNet libraries beside it are shadPS4 v0.20.0's with Awaken's changes
(`vendor/`, see SHADNET-PORT.md), as in Supermedo's build; this fork's earlier shadp2p-based
copies are gone. Without `BB_NET_BACKEND=thd` nothing in `thd/` runs.
