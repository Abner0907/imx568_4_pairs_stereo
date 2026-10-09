// imx568_sync_capture - start 8 IMX568 streams, drive the sync controller and
// emit time-aligned 8-frame sets (CLOCK_MONOTONIC mid-exposure timestamps).
//
//   imx568_sync_capture --mode 0 --fps 30 --exposure-us 4000
//       --sync-tty /dev/ttyACM0 --sync-gpio /dev/gpiochip0:12
//       --seconds 10 --save-every 30 --out /tmp/sets
#include <glob.h>
#include <poll.h>
#include <signal.h>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "multicam.hpp"

using namespace multicam;

static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int) { g_stop = 1; }

struct Opts {
    std::vector<std::string> devices;
    int mode = 0;
    uint32_t width = 1224, height = 1024;
    double fps = 30;
    std::vector<uint32_t> exposure_us{5000};
    int gain = -1;  // dB*10
    std::string sync_tty, sync_gpio;
    std::string sysfs_glob = "/sys/bus/i2c/drivers/imx568/*/trigger_offset_ns";
    double seconds = 0;
    int save_every = 0;
    std::string out = ".";
    int shift = 4;  // Xavier VI stores RAW12 MSB-aligned in 16 bit (verify with test pattern)
};

static std::vector<std::string> split(const std::string& s, char c) {
    std::vector<std::string> v;
    std::stringstream ss(s);
    std::string t;
    while (std::getline(ss, t, c))
        if (!t.empty()) v.push_back(t);
    return v;
}

static void usage() {
    std::cerr <<
        "options:\n"
        "  --devices /dev/video0,..   (default video0..video7; index = camera id, pair k = cams 2k,2k+1)\n"
        "  --mode 0|1                 0 = 1224x1024 2x2-binned, 1 = 2448x2048\n"
        "  --fps F                    trigger rate\n"
        "  --exposure-us E | E0,E1,E2,E3   per stereo pair\n"
        "  --gain G                   dB*10 (0..480)\n"
        "  --sync-tty /dev/ttyACMx    sync controller (omit if started elsewhere)\n"
        "  --sync-gpio CHIP:LINE      Xavier GPIO wired to SYNC_OUT (mid-exposure edges)\n"
        "  --seconds S  --save-every N  --out DIR  --shift BITS\n";
}

static Opts parse(int argc, char** argv) {
    Opts o;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) {
                usage();
                std::exit(2);
            }
            return argv[++i];
        };
        if (a == "--devices") o.devices = split(next(), ',');
        else if (a == "--mode") o.mode = std::stoi(next());
        else if (a == "--fps") o.fps = std::stod(next());
        else if (a == "--exposure-us") {
            o.exposure_us.clear();
            for (auto& s : split(next(), ',')) o.exposure_us.push_back(uint32_t(std::stoul(s)));
        } else if (a == "--gain") o.gain = std::stoi(next());
        else if (a == "--sync-tty") o.sync_tty = next();
        else if (a == "--sync-gpio") o.sync_gpio = next();
        else if (a == "--seconds") o.seconds = std::stod(next());
        else if (a == "--save-every") o.save_every = std::stoi(next());
        else if (a == "--out") o.out = next();
        else if (a == "--shift") o.shift = std::stoi(next());
        else {
            usage();
            std::exit(a == "-h" || a == "--help" ? 0 : 2);
        }
    }
    if (o.devices.empty())
        for (int i = 0; i < 8; i++) o.devices.push_back("/dev/video" + std::to_string(i));
    if (o.mode == 1) {
        o.width = 2448;
        o.height = 2048;
    }
    return o;
}

static std::string first_glob(const std::string& pat) {
    glob_t g{};
    std::string r;
    if (glob(pat.c_str(), 0, nullptr, &g) == 0 && g.gl_pathc) r = g.gl_pathv[0];
    globfree(&g);
    return r;
}

static void save_pgm(const std::string& path, const Frame& f, int shift) {
    std::ofstream o(path, std::ios::binary);
    o << "P5\n" << f.width << " " << f.height << "\n4095\n";
    std::vector<uint8_t> row(size_t(f.width) * 2);
    for (uint32_t y = 0; y < f.height; y++) {
        auto* src = reinterpret_cast<const uint16_t*>(reinterpret_cast<const uint8_t*>(f.data) +
                                                      size_t(y) * f.stride_bytes);
        for (uint32_t x = 0; x < f.width; x++) {
            uint16_t v = uint16_t(src[x] >> shift) & 0x0FFF;
            row[2 * x] = uint8_t(v >> 8);  // PGM 16-bit is big-endian
            row[2 * x + 1] = uint8_t(v);
        }
        o.write(reinterpret_cast<const char*>(row.data()), std::streamsize(row.size()));
    }
}

int main(int argc, char** argv) {
    Opts o = parse(argc, argv);
    signal(SIGINT, on_sigint);
    const int n = int(o.devices.size());
    const uint64_t period_ns = uint64_t(1e9 / o.fps);

    try {
        // 1) open + stream all cameras: sensors get configured and wait for XTRIG
        std::vector<std::unique_ptr<V4l2Camera>> cams;
        for (int i = 0; i < n; i++) {
            cams.emplace_back(new V4l2Camera(i, o.devices[size_t(i)]));
            cams.back()->open(o.width, o.height, o.mode);
            if (o.gain >= 0) cams.back()->set_ctrl("Gain", o.gain);
        }
        for (auto& c : cams) c->start();

        // 2) sensor timing -> sync controller
        std::unique_ptr<SyncController> mcu;
        if (!o.sync_tty.empty()) {
            mcu.reset(new SyncController(o.sync_tty));
            std::string off = first_glob(o.sysfs_glob);
            if (off.empty()) throw std::runtime_error("imx568 sysfs not found: " + o.sysfs_glob);
            std::string dir = off.substr(0, off.rfind('/'));
            std::string off_ns = read_text_file(dir + "/trigger_offset_ns");
            std::string minper = read_text_file(dir + "/min_trigger_period_ns");
            std::cerr << "sensor: exposure offset " << off_ns << " ns, min trigger period " << minper << " ns\n";
            auto chk = [&](const std::string& cmd) {
                std::string r = mcu->command(cmd);
                if (r.rfind("OK", 0) != 0) throw std::runtime_error("sync controller '" + cmd + "': " + r);
            };
            chk("STOP");
            chk("OFFSET " + off_ns);
            chk("MINPER " + minper);
            chk("FPS " + std::to_string(o.fps));
            for (int k = 0; k < 4; k++)
                chk("EXP " + std::to_string(k) + " " +
                    std::to_string(o.exposure_us[std::min<size_t>(size_t(k), o.exposure_us.size() - 1)]));
            chk("START");
        }
        std::unique_ptr<SyncGpio> gpio;
        if (!o.sync_gpio.empty()) {
            auto p = o.sync_gpio.find(':');
            gpio.reset(new SyncGpio(o.sync_gpio.substr(0, p), unsigned(std::stoul(o.sync_gpio.substr(p + 1)))));
        }

        // latency fallback (no GPIO): SOF ~ mid + E/2 + ~1 ms (tTGDLY + link)
        FrameSetAssembler asm_(n, period_ns, uint64_t(o.exposure_us[0]) * 500 + 1000000);
        std::ofstream csv;
        if (o.save_every > 0) {
            csv.open(o.out + "/sets.csv");
            csv << "set_id,t_mid_ns,t_from_gpio,present_mask,sof_spread_us\n";
        }

        uint64_t t_start = monotonic_ns(), t_report = t_start, sets_last = 0;
        std::vector<uint64_t> frames_per_cam(size_t(n), 0);
        double spread_max_us = 0;

        while (!g_stop) {
            std::vector<pollfd> pf;
            for (auto& c : cams) pf.push_back({c->fd(), POLLIN, 0});
            if (gpio) pf.push_back({gpio->fd(), POLLIN, 0});
            if (mcu) pf.push_back({mcu->fd(), POLLIN, 0});
            ::poll(pf.data(), pf.size(), 50);

            for (auto& c : cams)
                while (auto f = c->dequeue()) {
                    frames_per_cam[size_t(f->cam)]++;
                    asm_.push_frame(*f);
                }
            if (gpio)
                for (uint64_t t : gpio->read_events()) asm_.push_sync(t);
            if (mcu) mcu->read_lines();  // "F seq t_us E0..E3" - available for logging

            uint64_t now = monotonic_ns();
            for (auto& s : asm_.poll(now)) {
                spread_max_us = std::max(spread_max_us, s.sof_spread_ns / 1e3);
                if (o.save_every > 0 && s.id % uint64_t(o.save_every) == 0) {
                    for (auto& f : s.frames)
                        if (f.cam >= 0)
                            save_pgm(o.out + "/set" + std::to_string(s.id) + "_cam" + std::to_string(f.cam) + ".pgm",
                                     f, o.shift);
                    csv << s.id << "," << s.t_mid_ns << "," << s.t_from_gpio << "," << s.present_mask << ","
                        << s.sof_spread_ns / 1000 << "\n";
                }
                // >>> hand the set to your VIO front-end here (copy or process before requeue) <<<
                for (auto& f : s.frames)
                    if (f.cam >= 0) cams[size_t(f.cam)]->requeue(f);
            }
            for (auto& f : asm_.take_discarded()) cams[size_t(f.cam)]->requeue(f);

            if (now - t_report >= 1000000000ull) {
                double dt = (now - t_report) / 1e9;
                std::fprintf(stderr, "sets %.1f/s (complete %llu, partial %llu, late frames %llu) "
                                     "max SOF spread %.0f us | fps:",
                             (asm_.sets_complete + asm_.sets_partial - sets_last) / dt,
                             (unsigned long long)asm_.sets_complete, (unsigned long long)asm_.sets_partial,
                             (unsigned long long)asm_.frames_late, spread_max_us);
                for (auto& c : frames_per_cam) {
                    std::fprintf(stderr, " %.1f", c / dt);
                    c = 0;
                }
                std::fprintf(stderr, "\n");
                sets_last = asm_.sets_complete + asm_.sets_partial;
                spread_max_us = 0;
                t_report = now;
            }
            if (o.seconds > 0 && now - t_start > uint64_t(o.seconds * 1e9)) break;
        }
        if (mcu) mcu->command("STOP");
        for (auto& c : cams) c->stop();
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
