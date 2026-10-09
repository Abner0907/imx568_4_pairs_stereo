// Host-side test of FrameSetAssembler with synthetic trigger timing:
// 4 pairs with different exposures (mid-exposure aligned), per-link jitter,
// randomly dropped frames, and SYNC GPIO edges.
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <random>

#include "multicam.hpp"

using namespace multicam;

int main() {
    const int N = 8;
    const uint64_t period = 33333333;            // 30 fps
    const uint32_t exp_us[4] = {2000, 8000, 15000, 500};
    const uint64_t tgdly = 700000;               // ~ tTGDLY + GMSL latency
    FrameSetAssembler a(N, period, 2500000 + 1000000);
    std::mt19937 rng(1);
    std::uniform_int_distribution<int> jit(-30000, 30000);  // +-30 us SOF jitter
    std::uniform_real_distribution<double> u(0, 1);

    struct Ev { uint64_t t; int cam; bool sync; };
    std::vector<Ev> evs;
    const int TRIG = 300;
    int dropped = 0;
    for (int k = 0; k < TRIG; k++) {
        uint64_t mid = 1000000000ull + uint64_t(k) * period;
        evs.push_back({mid, -1, true});
        for (int c = 0; c < N; c++) {
            if (u(rng) < 0.01) { dropped++; continue; }
            uint64_t sof = mid + exp_us[c / 2] * 500ull + tgdly + uint64_t(int64_t(jit(rng)) + 30000);
            evs.push_back({sof, c, false});
        }
    }
    // frames are delivered in arrival order (sorted by time)
    std::sort(evs.begin(), evs.end(), [](const Ev& x, const Ev& y) { return x.t < y.t; });

    uint64_t sets = 0, wrong_ts = 0, frames_in_sets = 0;
    uint32_t seq[N] = {};
    for (auto& e : evs) {
        if (e.sync) a.push_sync(e.t);
        else {
            Frame f;
            f.cam = e.cam;
            f.sof_ns = e.t;
            f.sequence = seq[e.cam]++;
            a.push_frame(f);
        }
        for (auto& s : a.poll(e.t)) {
            sets++;
            for (auto& f : s.frames) if (f.cam >= 0) frames_in_sets++;
            // every frame's true trigger must equal the set's GPIO mid time
            for (auto& f : s.frames)
                if (f.cam >= 0) {
                    uint64_t k = (s.t_mid_ns - 1000000000ull) / period;
                    uint64_t mid = 1000000000ull + k * period;
                    if (!s.t_from_gpio || s.t_mid_ns != mid || f.sof_ns < mid || f.sof_ns - mid > period / 2)
                        wrong_ts++;
                }
        }
    }
    for (auto& s : a.poll(UINT64_MAX)) {
        sets++;
        for (auto& f : s.frames) if (f.cam >= 0) frames_in_sets++;
    }
    std::printf("triggers %d  sets %llu  complete %llu  partial %llu  late %llu  dropped %d  "
                "frames in sets %llu  wrong-timestamp frames %llu\n",
                TRIG, (unsigned long long)sets, (unsigned long long)a.sets_complete,
                (unsigned long long)a.sets_partial, (unsigned long long)a.frames_late, dropped,
                (unsigned long long)frames_in_sets, (unsigned long long)wrong_ts);
    assert(sets == uint64_t(TRIG));
    assert(a.frames_late == 0);
    assert(frames_in_sets == uint64_t(TRIG * N - dropped));
    assert(wrong_ts == 0);
    std::printf("PASS\n");
    return 0;
}
