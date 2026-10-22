// SPDX-License-Identifier: MIT
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace uwdev::mp3codec {

// Streaming, per-channel 96000 -> 48000 Hz causal anti-alias FIR decimator.
// The first output uses input time 0, then 2,4,... . finish() drains 191 zeros.
class Decimator2 {
public:
    Decimator2();
    std::vector<double> push(const double* samples, std::size_t count);
    std::vector<double> finish();
    // Bounded caller-owned storage; capacity is validated before state mutation.
    std::size_t push_into(const double* samples, std::size_t count, double* output, std::size_t capacity);
    std::size_t finish_into(double* output, std::size_t capacity);
    const std::array<double, 192>& coefficients() const { return taps(); }
    static constexpr double delay_input_samples = 95.5;
    static constexpr double delay_output_samples = 47.75;

private:
    static const std::array<double,192>& taps();
    std::array<double, 192> history_{};
    std::size_t cursor_ = 0;
    std::uint64_t samples_seen_ = 0;
    bool finished_ = false;
    std::size_t process(const double* samples, std::size_t count, double* output, std::size_t capacity);
};

} // namespace uwdev::mp3codec
