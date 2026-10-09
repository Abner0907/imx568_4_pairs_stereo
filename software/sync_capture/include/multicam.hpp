// Synchronized multi-camera capture for 8 x IMX568 (4 stereo pairs) on Jetson.
// No dependencies beyond the Linux UAPI (V4L2 + GPIO character device v2).
#pragma once

#include <cstdint>
#include <deque>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace multicam {

// ------------------------------------------------------------------ V4L2
struct Frame {
    int cam = -1;
    uint32_t sequence = 0;      // V4L2 sequence (per camera)
    uint64_t sof_ns = 0;        // V4L2 buffer timestamp, CLOCK_MONOTONIC (VI start-of-frame)
    int buf_index = -1;
    const uint16_t* data = nullptr;  // valid until requeue()
    uint32_t width = 0, height = 0, stride_bytes = 0;
};

class V4l2Camera {
public:
    V4l2Camera(int index, std::string dev);
    ~V4l2Camera();
    V4l2Camera(const V4l2Camera&) = delete;
    V4l2Camera& operator=(const V4l2Camera&) = delete;

    // RAW12 (exposed by L4T as SRGGB12; the IMX568 is mono -> treat as Y12)
    void open(uint32_t width, uint32_t height, int sensor_mode, unsigned nbufs = 6);
    void set_ctrl(const std::string& name, int64_t value, bool required = false);
    void start();
    void stop();
    std::optional<Frame> dequeue();   // non-blocking
    void requeue(const Frame& f);
    int fd() const { return fd_; }
    int index() const { return index_; }
    const std::string& path() const { return dev_; }

private:
    int index_;
    std::string dev_;
    int fd_ = -1;
    uint32_t w_ = 0, h_ = 0, stride_ = 0;
    struct Buf { void* p; size_t len; };
    std::vector<Buf> bufs_;
    bool streaming_ = false;
};

// ------------------------------------------------- sync pulse (Xavier GPIO)
// Rising edge of the controller's SYNC_OUT = common mid-exposure instant.
class SyncGpio {
public:
    SyncGpio(const std::string& chip, unsigned line);
    ~SyncGpio();
    int fd() const { return fd_; }
    // drains pending edges; returns their CLOCK_MONOTONIC timestamps
    std::vector<uint64_t> read_events();

private:
    int fd_ = -1;
};

// ------------------------------------------- sync controller (USB-CDC MCU)
class SyncController {
public:
    explicit SyncController(const std::string& tty);
    ~SyncController();
    std::string command(const std::string& cmd, int timeout_ms = 500);  // returns "OK ..." / "ERR ..."
    int fd() const { return fd_; }
    std::vector<std::string> read_lines();   // non-blocking ("F ..." reports)

private:
    int fd_ = -1;
    std::string rx_;
};

// --------------------------------------------------- frame-set assembly
struct FrameSet {
    uint64_t id = 0;
    uint64_t t_mid_ns = 0;          // mid-exposure (from SYNC GPIO) or estimate
    bool t_from_gpio = false;
    uint32_t present_mask = 0;      // bit i = camera i delivered a frame
    std::vector<Frame> frames;      // indexed by camera (cam == -1 if missing)
    uint64_t sof_spread_ns = 0;     // max-min SOF among present frames
};

// Groups frames that belong to the same trigger. Frames from one trigger
// reach VI within (Emax-Emin)/2 + link skew of each other (a few ms), far
// less than one trigger period, so clustering on SOF time is unambiguous.
class FrameSetAssembler {
public:
    FrameSetAssembler(int num_cams, uint64_t period_ns, uint64_t est_latency_ns);
    void push_frame(const Frame& f);
    void push_sync(uint64_t t_mid_ns);
    // emits complete sets, or incomplete ones once they are older than 1.5 periods
    std::vector<FrameSet> poll(uint64_t now_ns);
    // frames whose buffers can be returned without being part of an emitted set
    std::vector<Frame> take_discarded();

    uint64_t sets_complete = 0, sets_partial = 0, frames_late = 0;

private:
    FrameSet* find_or_open(const Frame& f);
    int n_;
    uint64_t period_, latency_;
    uint64_t next_id_ = 0;
    std::deque<FrameSet> open_;
    std::deque<uint64_t> syncs_;
    std::vector<Frame> discarded_;
    uint64_t last_emitted_sof_ = 0;
};

uint64_t monotonic_ns();
std::string read_text_file(const std::string& path);

}  // namespace multicam
