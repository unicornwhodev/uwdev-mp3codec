// SPDX-License-Identifier: MIT
#pragma once
#include "dsp.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>

namespace uwdev::mp3codec {

// Input order is [granule][channel], two 576-line granules per MPEG frame.
// Spectrum::values are MPEG reconstructed spectral units, not PCM samples.
class MpegWriter final {
public:
    using Sink = std::function<void(const std::uint8_t*, std::size_t)>;
    MpegWriter(int sample_rate, int channels, int bitrate_kbps, Sink sink);
    ~MpegWriter();
    MpegWriter(const MpegWriter&) = delete;
    MpegWriter& operator=(const MpegWriter&) = delete;
    void write_frame(const std::array<std::array<Spectrum, 2>, 2>& granules);
    void finish();
    std::uint64_t frame_count() const noexcept;
    std::uint64_t output_bytes() const noexcept;
    std::uint64_t reservoir_references() const noexcept;
    std::size_t peak_reservoir_bytes() const noexcept;
    double reconstruction_peak() const noexcept;
    std::uint64_t protected_frames() const noexcept;
    double minimum_peak_gain() const noexcept;
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace uwdev::mp3codec
