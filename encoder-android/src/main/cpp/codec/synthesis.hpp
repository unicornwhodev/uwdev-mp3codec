// SPDX-License-Identifier: MIT
#pragma once
#include "dsp.hpp"
#include <array>

namespace uwdev::mp3codec {
// Internal reconstruction monitor for this encoder's pure MPEG-1 blocks.
// No bitstream parsing, audio output API, or third-party decoder is included.
class SynthesisMonitor {
public:
    std::array<double,576> process(Spectrum spectrum);
    double peak(const Spectrum& spectrum);
private:
    std::array<std::array<double,18>,32> overlap_{};
    std::array<double,1024> fifo_{};
    std::array<double,21> interpolation_history_{};
    std::size_t interpolation_cursor_=0;
};
}
