// SPDX-License-Identifier: MIT
#include "resampler.hpp"
#include <cmath>
#include <limits>
#include <stdexcept>

namespace uwdev::mp3codec {
namespace {
constexpr double pi = 3.141592653589793238462643383279502884;

// Positive-argument power series for modified Bessel I0. For beta=8.6 this
// converges rapidly. The fixed bound and stop condition are deterministic.
double bessel_i0(double x) {
    const double quarter_square = x*x*0.25;
    double term = 1.0;
    double sum = 1.0;
    for (int k = 1; k <= 64; ++k) {
        term *= quarter_square/static_cast<double>(k*k);
        sum += term;
        if (term < sum*1e-17) break;
    }
    return sum;
}
}

Decimator2::Decimator2() = default;

const std::array<double,192>& Decimator2::taps() {
    static const auto result=[] {
    std::array<double,192> taps_{};
    constexpr double cutoff = 22000.0/96000.0;
    constexpr double beta = 8.6;
    const double normalization = bessel_i0(beta);
    double dc_gain = 0.0;
    for (std::size_t n = 0; n < taps_.size(); ++n) {
        const double offset = static_cast<double>(n)-95.5;
        const double radius = offset/95.5;
        const double window = bessel_i0(beta*std::sqrt(1.0-radius*radius))/normalization;
        taps_[n] = std::sin(2.0*pi*cutoff*offset)/(pi*offset)*window;
        dc_gain += taps_[n];
    }
    for (double& tap : taps_) tap /= dc_gain;
    return taps_;
    }();
    return result;
}

std::size_t Decimator2::process(const double* samples, std::size_t count, double* output, std::size_t capacity) {
    if (count > std::numeric_limits<std::uint64_t>::max()-samples_seen_) {
        throw std::overflow_error("resampler sample counter overflow");
    }
    const std::size_t required=count/2 + (samples_seen_%2 == 0 ? count%2 : 0);
    if (capacity<required || (required!=0 && output==nullptr)) throw std::invalid_argument("resampler output capacity is insufficient");
    const auto& filter=taps();
    std::size_t written=0;
    for (std::size_t n = 0; n < count; ++n) {
        history_[cursor_] = samples[n];
        if (samples_seen_%2 == 0) {
            double value = 0.0;
            std::size_t cursor = cursor_;
            for (std::size_t k = 0; k < filter.size(); ++k) {
                value += filter[k]*history_[cursor];
                cursor = cursor == 0 ? filter.size()-1 : cursor-1;
            }
            output[written++]=value;
        }
        cursor_ = (cursor_+1)%filter.size();
        ++samples_seen_;
    }
    return written;
}

std::vector<double> Decimator2::push(const double* samples, std::size_t count) {
    if (finished_) throw std::logic_error("resampler is already finalized");
    if (count != 0 && samples == nullptr) throw std::invalid_argument("null resampler input");
    std::vector<double> output(count/2 + count%2);
    output.resize(push_into(samples,count,output.data(),output.size()));
    return output;
}

std::size_t Decimator2::push_into(const double* samples, std::size_t count, double* output, std::size_t capacity) {
    if (finished_) throw std::logic_error("resampler is already finalized");
    if (count != 0 && samples == nullptr) throw std::invalid_argument("null resampler input");
    for (std::size_t n = 0; n < count; ++n) {
        if (!std::isfinite(samples[n])) throw std::invalid_argument("non-finite resampler input");
    }
    return process(samples, count, output, capacity);
}

std::vector<double> Decimator2::finish() {
    std::array<double,96> output{};
    const auto count=finish_into(output.data(),output.size());
    return {output.begin(),output.begin()+static_cast<std::ptrdiff_t>(count)};
}

std::size_t Decimator2::finish_into(double* output, std::size_t capacity) {
    if (finished_) return 0;
    if (samples_seen_ == 0) { finished_=true;return 0; }
    const std::array<double, 191> zeros{};
    const auto written=process(zeros.data(), zeros.size(), output, capacity);
    finished_=true;
    return written;
}

} // namespace uwdev::mp3codec
