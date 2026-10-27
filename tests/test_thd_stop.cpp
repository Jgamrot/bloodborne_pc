// SPDX-License-Identifier: GPL-3.0-or-later
// The Hunter's Dream refusing this build (gpu/bbnet/thd/thd_stop.h): the first refused request
// stops the rest, before and after the server has answered once; no server needed.
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <thread>
#include <vector>
#include "thd_stop.h"

using namespace std::chrono_literals;

int main() {
    assert(BbThd::IsClientRefusal("This client is not supported on The Hunter's Dream"));
    assert(BbThd::IsClientRefusal("THIS CLIENT IS NOT SUPPORTED"));
    assert(!BbThd::IsClientRefusal("Token expired"));
    assert(!BbThd::IsClientRefusal("Ruleset hard is not supported"));
    assert(!BbThd::IsClientRefusal(""));

    {
        // Before any answer: eight requests at once reach the server one at a time; the first
        // is refused and stops the gate, so none of the other seven is sent.
        BbThd::TrafficGate gate;
        std::atomic<int> sent{0}, inside{0}, most{0}, refused{0};
        auto request = [&] {
            const bool ran = gate.Run([&] {
                const int now = ++inside;
                most = std::max(most.load(), now);
                std::this_thread::sleep_for(20ms);
                ++sent;
                gate.Stop();
                --inside;
                return 401;
            });
            if (!ran) ++refused;
        };
        std::vector<std::thread> threads;
        for (int i = 0; i < 8; ++i) threads.emplace_back(request);
        for (auto& t : threads) t.join();
        assert(sent == 1 && refused == 7 && most == 1);
        assert(gate.Stopped());
        assert(!gate.Run([] { return 200; }));
    }
    {
        // Without an answer (network down) the gate stays one at a time and nothing stops it.
        BbThd::TrafficGate gate;
        int calls = 0;
        for (int i = 0; i < 3; ++i) {
            assert(gate.Run([&] {
                ++calls;
                return 0;
            }));
        }
        assert(calls == 3 && !gate.Stopped());
        // An accepted answer lets requests run side by side: a long poll does not hold the rest.
        assert(gate.Run([] { return 200; }));
        std::mutex mu;
        std::condition_variable cv;
        int waiting = 0;
        bool both = false;
        auto request = [&] {
            gate.Run([&] {
                std::unique_lock lk(mu);
                if (++waiting == 2) cv.notify_all();
                both = cv.wait_for(lk, 2s, [&] { return waiting == 2; });
                return 200;
            });
        };
        std::thread a(request), b(request);
        a.join();
        b.join();
        assert(both);
        // A refusal after that: the stop holds for every later request.
        assert(gate.Stop() && !gate.Stop());
        assert(!gate.Run([] { return 200; }));
    }
    std::puts("THD stop: first refusal stops the rest, one at a time until answered, long polls not held PASS");
}
