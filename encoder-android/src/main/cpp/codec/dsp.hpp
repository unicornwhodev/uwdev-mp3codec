// SPDX-License-Identifier: MIT
#pragma once
#include <array>
#include <cstddef>

namespace uwdev::mp3codec {

enum class BlockType : int { Normal = 0, Start = 1, Short = 2, Stop = 3 };

struct Spectrum {
    // Long: subband*18 + frequency; short: subband*18 + frequency*3 + window.
    // The latter must be reordered by short scalefactor bands before Huffman coding.
    // MPEG reconstruction units, with normalized [-1,1] PCM at the input.
    std::array<double, 576> values{};
    BlockType block_type = BlockType::Normal;
    // Mean permitted quantization-noise power per long scalefactor band.
    std::array<double, 22> masking{};
};

struct AnalysisTables;
class AnalysisBank {
public:
    explicit AnalysisBank(int sample_rate = 44100);
    Spectrum process(const std::array<double, 576>& pcm, bool next_transient = false);
    static bool transient(const std::array<double, 576>& pcm) noexcept;
    static bool transient_between(const std::array<double, 576>& current,
                                  const std::array<double, 576>& next) noexcept;
    // Analysis/synthesis polyphase pair delay, excluding hybrid MDCT and buffering.
    static constexpr std::size_t polyphase_pair_delay = 480;

private:
    int sample_rate_;
    std::array<double, 512> history_{};
    std::array<std::array<double, 18>, 32> previous_subbands_{};
    const AnalysisTables* tables_;
    BlockType previous_type_ = BlockType::Normal;
    void estimate_masking(Spectrum& spectrum) const;
};

} // namespace uwdev::mp3codec
