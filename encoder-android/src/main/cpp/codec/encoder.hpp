// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Unicorn Who Dev
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <stdexcept>

namespace uwdev::mp3codec {

struct Config {
    int input_sample_rate;
    int channels;
    int bitrate_kbps;
};

struct Stats {
    std::uint64_t input_frames = 0;
    std::uint64_t output_bytes = 0;
    std::uint64_t encoded_mpeg_frames = 0;
    int output_sample_rate = 0;
    int bitrate_kbps = 0;
    int channels = 0;
    // Diagnostics appended after the original six statistics in the private JNI payload.
    double reconstructed_peak = 0;
    std::uint64_t peak_protected_frames = 0;
    double minimum_peak_gain = 1;
};

class Cancelled : public std::runtime_error {
public:
    Cancelled() : std::runtime_error("MP3 encoding cancelled") {}
};

// One producer per instance. Only request_cancel() may overlap other calls.
// The caller must keep this object alive until all calls have returned.
class Encoder final {
public:
    using Sink = std::function<void(const std::uint8_t*, std::size_t)>;
    Encoder(Config config, Sink sink);
    ~Encoder();
    Encoder(const Encoder&) = delete;
    Encoder& operator=(const Encoder&) = delete;
    Encoder(Encoder&&) = delete;
    Encoder& operator=(Encoder&&) = delete;

    // bytes must contain whole interleaved PCM16 frames; empty writes are valid.
    void write_pcm16le(const std::uint8_t* data, std::size_t bytes);
    Stats finish();
    void request_cancel() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace uwdev::mp3codec
