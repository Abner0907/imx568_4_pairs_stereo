#include "multicam.hpp"

#include <fcntl.h>
#include <linux/gpio.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <termios.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <ctime>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace multicam {

static int xioctl(int fd, unsigned long req, void* arg) {
    int r;
    do {
        r = ioctl(fd, req, arg);
    } while (r == -1 && errno == EINTR);
    return r;
}

[[noreturn]] static void fail(const std::string& what) {
    throw std::runtime_error(what + ": " + std::strerror(errno));
}

uint64_t monotonic_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return uint64_t(ts.tv_sec) * 1000000000ull + uint64_t(ts.tv_nsec);
}

std::string read_text_file(const std::string& path) {
    std::ifstream f(path);
    std::stringstream ss;
    ss << f.rdbuf();
    std::string s = ss.str();
    while (!s.empty() && (s.back() == '\n' || s.back() == ' ')) s.pop_back();
    return s;
}

// ================================================================ V4L2
V4l2Camera::V4l2Camera(int index, std::string dev) : index_(index), dev_(std::move(dev)) {}

V4l2Camera::~V4l2Camera() {
    try {
        stop();
    } catch (...) {
    }
    for (auto& b : bufs_) munmap(b.p, b.len);
    if (fd_ >= 0) ::close(fd_);
}

void V4l2Camera::set_ctrl(const std::string& name, int64_t value, bool required) {
    v4l2_query_ext_ctrl q{};
    q.id = V4L2_CTRL_FLAG_NEXT_CTRL | V4L2_CTRL_FLAG_NEXT_COMPOUND;
    while (xioctl(fd_, VIDIOC_QUERY_EXT_CTRL, &q) == 0) {
        if (name == q.name) {
            v4l2_ext_control c{};
            c.id = q.id;
            c.value64 = value;
            v4l2_ext_controls cs{};
            cs.which = V4L2_CTRL_WHICH_CUR_VAL;
            cs.count = 1;
            cs.controls = &c;
            if (q.type != V4L2_CTRL_TYPE_INTEGER64) c.value = int32_t(value);
            if (xioctl(fd_, VIDIOC_S_EXT_CTRLS, &cs) < 0) fail(dev_ + " set '" + name + "'");
            return;
        }
        q.id |= V4L2_CTRL_FLAG_NEXT_CTRL | V4L2_CTRL_FLAG_NEXT_COMPOUND;
    }
    if (required) throw std::runtime_error(dev_ + ": control '" + name + "' not found");
}

void V4l2Camera::open(uint32_t width, uint32_t height, int sensor_mode, unsigned nbufs) {
    fd_ = ::open(dev_.c_str(), O_RDWR | O_NONBLOCK);
    if (fd_ < 0) fail("open " + dev_);

    // L4T: raw capture through VI without Argus/ISP
    set_ctrl("Bypass Mode", 0);
    if (sensor_mode >= 0) set_ctrl("Sensor Mode", sensor_mode);

    v4l2_format fmt{};
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = width;
    fmt.fmt.pix.height = height;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_SRGGB12;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(fd_, VIDIOC_S_FMT, &fmt) < 0) fail(dev_ + " S_FMT");
    if (fmt.fmt.pix.width != width || fmt.fmt.pix.height != height)
        throw std::runtime_error(dev_ + ": driver chose " + std::to_string(fmt.fmt.pix.width) + "x" +
                                 std::to_string(fmt.fmt.pix.height));
    w_ = width;
    h_ = height;
    stride_ = fmt.fmt.pix.bytesperline ? fmt.fmt.pix.bytesperline : width * 2;

    v4l2_requestbuffers rb{};
    rb.count = nbufs;
    rb.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    rb.memory = V4L2_MEMORY_MMAP;
    if (xioctl(fd_, VIDIOC_REQBUFS, &rb) < 0) fail(dev_ + " REQBUFS");
    for (unsigned i = 0; i < rb.count; i++) {
        v4l2_buffer b{};
        b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        b.memory = V4L2_MEMORY_MMAP;
        b.index = i;
        if (xioctl(fd_, VIDIOC_QUERYBUF, &b) < 0) fail(dev_ + " QUERYBUF");
        void* p = mmap(nullptr, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, b.m.offset);
        if (p == MAP_FAILED) fail(dev_ + " mmap");
        bufs_.push_back({p, b.length});
        if (xioctl(fd_, VIDIOC_QBUF, &b) < 0) fail(dev_ + " QBUF");
    }
}

void V4l2Camera::start() {
    v4l2_buf_type t = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd_, VIDIOC_STREAMON, &t) < 0) fail(dev_ + " STREAMON");
    streaming_ = true;
}

void V4l2Camera::stop() {
    if (!streaming_) return;
    v4l2_buf_type t = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    xioctl(fd_, VIDIOC_STREAMOFF, &t);
    streaming_ = false;
}

std::optional<Frame> V4l2Camera::dequeue() {
    v4l2_buffer b{};
    b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    b.memory = V4L2_MEMORY_MMAP;
    if (xioctl(fd_, VIDIOC_DQBUF, &b) < 0) {
        if (errno == EAGAIN) return std::nullopt;
        fail(dev_ + " DQBUF");
    }
    if (b.flags & V4L2_BUF_FLAG_ERROR) {  // corrupted frame: give it straight back
        xioctl(fd_, VIDIOC_QBUF, &b);
        return std::nullopt;
    }
    Frame f;
    f.cam = index_;
    f.sequence = b.sequence;
    f.sof_ns = uint64_t(b.timestamp.tv_sec) * 1000000000ull + uint64_t(b.timestamp.tv_usec) * 1000ull;
    f.buf_index = int(b.index);
    f.data = static_cast<const uint16_t*>(bufs_[b.index].p);
    f.width = w_;
    f.height = h_;
    f.stride_bytes = stride_;
    return f;
}

void V4l2Camera::requeue(const Frame& f) {
    v4l2_buffer b{};
    b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    b.memory = V4L2_MEMORY_MMAP;
    b.index = uint32_t(f.buf_index);
    if (xioctl(fd_, VIDIOC_QBUF, &b) < 0) fail(dev_ + " re-QBUF");
}

// ================================================================ GPIO
SyncGpio::SyncGpio(const std::string& chip, unsigned line) {
    int cfd = ::open(chip.c_str(), O_RDONLY);
    if (cfd < 0) fail("open " + chip);
    gpio_v2_line_request req{};
    req.offsets[0] = line;
    req.num_lines = 1;
    req.config.flags = GPIO_V2_LINE_FLAG_INPUT | GPIO_V2_LINE_FLAG_EDGE_RISING;  // monotonic ts
    req.event_buffer_size = 64;
    std::strncpy(req.consumer, "imx568-sync", sizeof(req.consumer) - 1);
    int r = xioctl(cfd, GPIO_V2_GET_LINE_IOCTL, &req);
    ::close(cfd);
    if (r < 0) fail("GPIO_V2_GET_LINE " + chip + ":" + std::to_string(line));
    fd_ = req.fd;
    fcntl(fd_, F_SETFL, fcntl(fd_, F_GETFL) | O_NONBLOCK);
}

SyncGpio::~SyncGpio() {
    if (fd_ >= 0) ::close(fd_);
}

std::vector<uint64_t> SyncGpio::read_events() {
    std::vector<uint64_t> out;
    gpio_v2_line_event ev[16];
    for (;;) {
        ssize_t n = ::read(fd_, ev, sizeof(ev));
        if (n <= 0) break;
        for (size_t i = 0; i < size_t(n) / sizeof(ev[0]); i++) out.push_back(ev[i].timestamp_ns);
    }
    return out;
}

// ======================================================== sync controller
SyncController::SyncController(const std::string& tty) {
    fd_ = ::open(tty.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd_ < 0) fail("open " + tty);
    termios t{};
    tcgetattr(fd_, &t);
    cfmakeraw(&t);
    cfsetspeed(&t, B115200);  // ignored by USB-CDC, harmless
    tcsetattr(fd_, TCSANOW, &t);
    tcflush(fd_, TCIOFLUSH);
}

SyncController::~SyncController() {
    if (fd_ >= 0) ::close(fd_);
}

std::vector<std::string> SyncController::read_lines() {
    char buf[512];
    ssize_t n;
    while ((n = ::read(fd_, buf, sizeof buf)) > 0) rx_.append(buf, size_t(n));
    std::vector<std::string> lines;
    size_t pos;
    while ((pos = rx_.find('\n')) != std::string::npos) {
        std::string l = rx_.substr(0, pos);
        if (!l.empty() && l.back() == '\r') l.pop_back();
        lines.push_back(l);
        rx_.erase(0, pos + 1);
    }
    return lines;
}

std::string SyncController::command(const std::string& cmd, int timeout_ms) {
    std::string s = cmd + "\n";
    if (::write(fd_, s.data(), s.size()) != ssize_t(s.size())) fail("write sync controller");
    uint64_t deadline = monotonic_ns() + uint64_t(timeout_ms) * 1000000ull;
    while (monotonic_ns() < deadline) {
        pollfd p{fd_, POLLIN, 0};
        poll(&p, 1, 20);
        for (auto& l : read_lines())
            if (l.rfind("OK", 0) == 0 || l.rfind("ERR", 0) == 0 || l.rfind("PONG", 0) == 0) return l;
    }
    throw std::runtime_error("sync controller: no reply to '" + cmd + "'");
}

// ======================================================= set assembler
FrameSetAssembler::FrameSetAssembler(int num_cams, uint64_t period_ns, uint64_t est_latency_ns)
    : n_(num_cams), period_(period_ns), latency_(est_latency_ns) {}

FrameSet* FrameSetAssembler::find_or_open(const Frame& f) {
    for (auto& s : open_) {
        // anchor = earliest SOF in the set
        uint64_t anchor = UINT64_MAX;
        for (auto& fr : s.frames)
            if (fr.cam >= 0) anchor = std::min(anchor, fr.sof_ns);
        uint64_t d = f.sof_ns > anchor ? f.sof_ns - anchor : anchor - f.sof_ns;
        if (d < period_ / 2) {
            if (s.present_mask & (1u << f.cam)) return nullptr;  // duplicate cam in window
            return &s;
        }
    }
    FrameSet s;
    s.id = next_id_++;
    s.frames.assign(size_t(n_), Frame{});
    // keep open_ sorted by time
    auto it = std::find_if(open_.begin(), open_.end(), [&](const FrameSet& o) {
        for (auto& fr : o.frames)
            if (fr.cam >= 0) return fr.sof_ns > f.sof_ns;
        return false;
    });
    return &*open_.insert(it, std::move(s));
}

void FrameSetAssembler::push_frame(const Frame& f) {
    if (f.cam < 0 || f.cam >= n_) return;
    if (last_emitted_sof_ && f.sof_ns < last_emitted_sof_ + period_ / 2) {
        frames_late++;
        discarded_.push_back(f);
        return;
    }
    FrameSet* s = find_or_open(f);
    if (!s) {
        frames_late++;
        discarded_.push_back(f);
        return;
    }
    s->frames[size_t(f.cam)] = f;
    s->present_mask |= 1u << f.cam;
}

void FrameSetAssembler::push_sync(uint64_t t) {
    syncs_.push_back(t);
    while (syncs_.size() > 64) syncs_.pop_front();
}

std::vector<FrameSet> FrameSetAssembler::poll(uint64_t now) {
    std::vector<FrameSet> out;
    const uint32_t all = (n_ >= 32) ? 0xFFFFFFFFu : ((1u << n_) - 1);
    while (!open_.empty()) {
        FrameSet& s = open_.front();
        uint64_t lo = UINT64_MAX, hi = 0;
        for (auto& fr : s.frames)
            if (fr.cam >= 0) {
                lo = std::min(lo, fr.sof_ns);
                hi = std::max(hi, fr.sof_ns);
            }
        bool complete = s.present_mask == all;
        bool expired = now > lo && now - lo > period_ + period_ / 2;
        if (!complete && !expired) break;

        s.sof_spread_ns = hi - lo;
        // mid-exposure precedes every SOF of its trigger by < one period
        s.t_from_gpio = false;
        for (auto it = syncs_.rbegin(); it != syncs_.rend(); ++it) {
            if (*it <= lo && lo - *it < period_) {
                s.t_mid_ns = *it;
                s.t_from_gpio = true;
                break;
            }
        }
        if (!s.t_from_gpio) s.t_mid_ns = lo > latency_ ? lo - latency_ : 0;
        while (!syncs_.empty() && syncs_.front() <= s.t_mid_ns) syncs_.pop_front();

        (complete ? sets_complete : sets_partial)++;
        last_emitted_sof_ = hi;
        out.push_back(std::move(s));
        open_.pop_front();
    }
    return out;
}

std::vector<Frame> FrameSetAssembler::take_discarded() {
    std::vector<Frame> d;
    d.swap(discarded_);
    return d;
}

}  // namespace multicam
