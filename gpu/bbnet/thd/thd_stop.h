// SPDX-License-Identifier: GPL-3.0-or-later
// The Hunter's Dream backend: when the server refuses this build, nothing more goes to it this
// session. Header-only for tests/test_thd_stop.cpp.
#pragma once

#include <algorithm>
#include <atomic>
#include <cctype>
#include <mutex>
#include <string>

namespace BbThd {

// "This client is not supported ...": the server refuses this build (the User-Agent), not the
// account, so a new sign-in gets the same answer (thd_client_refused in the launcher).
inline bool IsClientRefusal(std::string reason) {
    std::transform(reason.begin(), reason.end(), reason.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    return reason.find("client is not supported") != std::string::npos;
}

// Until the server has answered once, its requests go one at a time, so a refusal stops the
// others before they are sent; once stopped, none is sent.
class TrafficGate {
public:
    // send() returns the HTTP status, 0 without an answer. False: stopped, send() not called.
    template <typename Send>
    bool Run(Send&& send) {
        std::unique_lock<std::mutex> first;
        if (!answered_.load()) first = std::unique_lock<std::mutex>(mu_);
        if (stopped_.load()) return false;
        if (send() > 0) answered_.store(true);
        return true;
    }
    // True for the call that stopped it.
    bool Stop() { return !stopped_.exchange(true); }
    bool Stopped() const { return stopped_.load(); }

private:
    std::mutex mu_;
    std::atomic<bool> answered_{false};
    std::atomic<bool> stopped_{false};
};

} // namespace BbThd
