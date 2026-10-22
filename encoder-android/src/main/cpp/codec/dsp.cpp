// SPDX-License-Identifier: MIT
#include "dsp.hpp"
#include "synthesis_window.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace uwdev::mp3codec {
namespace {
constexpr double pi = 3.141592653589793238462643383279502884;
constexpr std::array<int, 23> bands44100 = {
    0,4,8,12,16,20,24,30,36,44,52,62,74,90,110,134,162,196,238,288,342,418,576
};
constexpr std::array<int, 23> bands48000 = {
    0,4,8,12,16,20,24,30,36,42,50,60,72,88,106,128,156,190,230,276,330,384,576
};
// Standard alias-butterfly parameters, not encoder-specific heuristics.
constexpr std::array<double, 8> alias_c = { -0.6,-0.535,-0.33,-0.185,-0.095,-0.041,-0.0142,-0.0037 };
}

struct AnalysisTables {
    std::array<std::array<double,64>,32> cosine_{};
    std::array<std::array<double,36>,18> long_mdct_{};
    std::array<std::array<double,12>,6> short_mdct_{};
    std::array<std::array<double,36>,4> windows_{};
    AnalysisTables();
};

AnalysisTables::AnalysisTables() {
    for (std::size_t sb = 0; sb < 32; ++sb) {
        for (std::size_t n = 0; n < 64; ++n) {
            cosine_[sb][n] = std::cos(pi / 64.0 * static_cast<double>((2*sb+1)*(n+16)));
        }
    }
    for (std::size_t k = 0; k < 18; ++k) {
        for (std::size_t n = 0; n < 36; ++n) {
            long_mdct_[k][n] = std::cos(pi / 72.0 * static_cast<double>((2*n+19)*(2*k+1))) / 9.0;
        }
    }
    for (std::size_t k = 0; k < 6; ++k) {
        for (std::size_t n = 0; n < 12; ++n) {
            short_mdct_[k][n] = std::cos(pi / 24.0 * static_cast<double>((2*n+7)*(2*k+1))) / 3.0;
        }
    }
    for (std::size_t n = 0; n < 36; ++n) {
        const double full = std::sin(pi / 36.0 * (static_cast<double>(n)+0.5));
        windows_[0][n] = full;
        windows_[1][n] = n < 18 ? full : n < 24 ? 1.0 : n < 30 ?
            std::sin(pi / 12.0 * (static_cast<double>(n)-17.5)) : 0.0;
        windows_[3][n] = n < 6 ? 0.0 : n < 12 ?
            std::sin(pi / 12.0 * (static_cast<double>(n)-5.5)) : n < 18 ? 1.0 : full;
        windows_[2][n] = n < 12 ? std::sin(pi / 12.0 * (static_cast<double>(n)+0.5)) : 0.0;
    }
}

namespace {
const AnalysisTables& shared_analysis_tables() {
    static const AnalysisTables tables;
    return tables;
}
}

AnalysisBank::AnalysisBank(int sample_rate) : sample_rate_(sample_rate), tables_(&shared_analysis_tables()) {
    if (sample_rate != 44100 && sample_rate != 48000)
        throw std::invalid_argument("AnalysisBank requires 44100 or 48000 Hz");
}

bool AnalysisBank::transient(const std::array<double, 576>& pcm) noexcept {
    // Compare successive 64-sample high-pass energies. Derivative emphasis
    // reduces spurious switching on a slowly varying bass fundamental.
    std::array<double, 9> energy{};
    double last = pcm[0];
    double maximum = 0.0;
    for (std::size_t n = 0; n < pcm.size(); ++n) {
        const double delta = pcm[n] - last;
        energy[n/64] += delta*delta + 0.05*pcm[n]*pcm[n];
        maximum = std::max(maximum, std::abs(pcm[n]));
        last = pcm[n];
    }
    if (maximum < 0.002) return false;
    double history = energy[0];
    for (std::size_t part = 1; part < energy.size(); ++part) {
        if (energy[part] > 8.0*std::max(history, 1e-7) && energy[part] > 1e-4) return true;
        history = std::max(energy[part], history*0.55);
    }
    return false;
}

bool AnalysisBank::transient_between(const std::array<double, 576>& current,
                                     const std::array<double, 576>& next) noexcept {
    if (transient(next)) return true;
    double before = 0.0;
    double after = 0.0;
    double previous = current[511];
    for (std::size_t n = 512; n < 576; ++n) {
        const double difference = current[n]-previous;
        before += difference*difference+0.05*current[n]*current[n];
        previous = current[n];
    }
    for (std::size_t n = 0; n < 64; ++n) {
        const double difference = next[n]-previous;
        after += difference*difference+0.05*next[n]*next[n];
        previous = next[n];
    }
    return after > 8.0*std::max(before, 1e-7) && after > 1e-4;
}

Spectrum AnalysisBank::process(const std::array<double, 576>& pcm, bool next_transient) {
    for (const double sample : pcm) {
        if (!std::isfinite(sample)) throw std::invalid_argument("non-finite PCM");
    }
    Spectrum result;
    switch (previous_type_) {
        case BlockType::Normal:
            result.block_type = next_transient ? BlockType::Start : BlockType::Normal;
            break;
        case BlockType::Start:
            result.block_type = BlockType::Short;
            break;
        case BlockType::Short:
            result.block_type = (next_transient || transient(pcm)) ? BlockType::Short : BlockType::Stop;
            break;
        case BlockType::Stop:
            result.block_type = next_transient ? BlockType::Start : BlockType::Normal;
            break;
    }
    std::array<std::array<double, 18>, 32> current{};
    for (std::size_t slot = 0; slot < 18; ++slot) {
        std::move(history_.begin()+32, history_.end(), history_.begin());
        std::copy_n(pcm.begin()+static_cast<std::ptrdiff_t>(slot*32), 32, history_.begin()+480);
        // The time-reversed analysis bank is the normalized transpose of the
        // standard synthesis polyphase matrix. Grouping by n mod 64 factors
        // the common cosine out of the eight 64-sample phases.
        std::array<double, 64> phases{};
        for (std::size_t n = 0; n < 512; ++n) {
            phases[n%64] += history_[n] * static_cast<double>(detail::synthesis_window_q16[n]) / 2097152.0;
        }
        for (std::size_t sb = 0; sb < 32; ++sb) {
            double value = 0.0;
            for (std::size_t n = 0; n < 64; ++n) value += phases[n]*tables_->cosine_[sb][n];
            // The inverse hybrid stage changes sign on odd/odd samples too.
            current[sb][slot] = (sb%2 != 0 && slot%2 != 0) ? -value : value;
        }
    }
    const auto window_type = static_cast<std::size_t>(result.block_type);
    for (std::size_t sb = 0; sb < 32; ++sb) {
        std::array<double, 36> sequence{};
        std::copy(previous_subbands_[sb].begin(), previous_subbands_[sb].end(), sequence.begin());
        std::copy(current[sb].begin(), current[sb].end(), sequence.begin()+18);
        if (result.block_type == BlockType::Short) {
            for (std::size_t w = 0; w < 3; ++w) {
                for (std::size_t k = 0; k < 6; ++k) {
                    double value = 0.0;
                    for (std::size_t n = 0; n < 12; ++n) {
                        value += sequence[6+6*w+n]*tables_->windows_[2][n]*tables_->short_mdct_[k][n];
                    }
                    result.values[sb*18+3*k+w] = value;
                }
            }
        } else {
            for (std::size_t k = 0; k < 18; ++k) {
                double value = 0.0;
                for (std::size_t n = 0; n < 36; ++n) {
                    value += sequence[n]*tables_->windows_[window_type][n]*tables_->long_mdct_[k][n];
                }
                result.values[sb*18+k] = value;
            }
        }
    }
    // Apply the inverse of the decoder's orthogonal alias butterflies.
    if (result.block_type != BlockType::Short) {
        for (std::size_t sb = 1; sb < 32; ++sb) {
            for (std::size_t k = 0; k < 8; ++k) {
                const double cs = 1.0/std::sqrt(1.0+alias_c[k]*alias_c[k]);
                const double ca = alias_c[k]*cs;
                const std::size_t low = sb*18-1-k;
                const std::size_t high = sb*18+k;
                const double a = result.values[low];
                const double b = result.values[high];
                result.values[low] = a*cs+b*ca;
                result.values[high] = b*cs-a*ca;
            }
        }
    }
    previous_subbands_ = current;
    previous_type_ = result.block_type;
    estimate_masking(result);
    return result;
}

void AnalysisBank::estimate_masking(Spectrum& spectrum) const {
    const auto& bands = sample_rate_ == 44100 ? bands44100 : bands48000;
    std::array<double, 22> mean_power{};
    std::array<double, 22> tonality{};
    for (std::size_t band = 0; band < 22; ++band) {
        double logarithms = 0.0;
        for (int k = bands[band]; k < bands[band+1]; ++k) {
            const double value = spectrum.values[static_cast<std::size_t>(k)];
            const double power = value*value;
            mean_power[band] += power;
            logarithms += std::log(std::max(power, 1e-30));
        }
        const double count = static_cast<double>(bands[band+1]-bands[band]);
        mean_power[band] /= count;
        const double flatness = std::exp(logarithms/count)/std::max(mean_power[band], 1e-30);
        tonality[band] = 1.0-std::clamp(flatness, 0.0, 1.0);
    }
    // A deliberately conservative, local masking model. Tonal energy permits
    // less distortion than noise-like energy, with asymmetric neighbour spread.
    // This is an encoder policy, not a claim to implement ISO psycho model 1/2.
    for (std::size_t band = 0; band < 22; ++band) {
        const double own = mean_power[band] * std::pow(10.0, -(18.0+14.0*tonality[band])/10.0);
        const double below = band > 0 ? mean_power[band-1]*0.00020 : 0.0;
        const double above = band+1 < 22 ? mean_power[band+1]*0.00005 : 0.0;
        spectrum.masking[band] = std::max(1e-14, own+below+above);
    }
}

} // namespace uwdev::mp3codec
