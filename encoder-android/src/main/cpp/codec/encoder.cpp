// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Unicorn Who Dev
#include "encoder.hpp"
#include "dsp.hpp"
#include "mpeg.hpp"
#include "resampler.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <deque>
#include <limits>
#include <utility>

namespace uwdev::mp3codec {
namespace {
Config validate(Config c) {
    if (c.input_sample_rate != 44100 && c.input_sample_rate != 48000 && c.input_sample_rate != 96000)
        throw std::invalid_argument("inputSampleRate must be 44100, 48000 or 96000 Hz");
    if (c.channels != 1 && c.channels != 2)
        throw std::invalid_argument("channels must be 1 or 2");
    if (c.bitrate_kbps != 128 && c.bitrate_kbps != 192 && c.bitrate_kbps != 256 && c.bitrate_kbps != 320)
        throw std::invalid_argument("bitrateKbps must be 128, 192, 256 or 320");
    return c;
}
int output_rate(const Config& c) { return c.input_sample_rate == 96000 ? 48000 : c.input_sample_rate; }
double read_sample(const std::uint8_t* p) {
    const unsigned u = static_cast<unsigned>(p[0]) | (static_cast<unsigned>(p[1]) << 8U);
    const int s = u >= 32768U ? static_cast<int>(u) - 65536 : static_cast<int>(u);
    return static_cast<double>(s) / 32768.0;
}
} // namespace

struct Encoder::Impl {
    enum class State { Open, Finished, Failed };
    using Block = std::array<std::array<double, 576>, 2>;
    Config config;
    Sink sink;
    std::atomic<bool> cancelled{false};
    State state = State::Open;
    Stats stats;
    std::array<AnalysisBank, 2> banks;
    std::array<Decimator2, 2> decimators;
    std::deque<Block> lookahead;
    Block assembling{};
    std::size_t position = 0;
    std::array<std::array<Spectrum, 2>, 2> spectra{};
    std::size_t granule = 0;
    MpegWriter writer;

    Impl(Config cfg, Sink destination)
        : config(validate(cfg)), sink(std::move(destination)),
          banks{{AnalysisBank(output_rate(config)), AnalysisBank(output_rate(config))}},
          writer(output_rate(config), config.channels, config.bitrate_kbps,
                 [this](const std::uint8_t* p, std::size_t n) {
                     check_cancelled();
                     sink(p, n);
                     check_cancelled();
                 }) {
        if (!sink) throw std::invalid_argument("Output sink must not be empty");
        stats.output_sample_rate = output_rate(config);
        stats.channels = config.channels;
        stats.bitrate_kbps = config.bitrate_kbps;
    }

    void check_cancelled() const {
        if (cancelled.load(std::memory_order_relaxed)) throw Cancelled();
    }
    void check_open() const {
        check_cancelled();
        if (state != State::Open) throw std::runtime_error("Encoder no longer accepts PCM");
    }
    void process_front() {
        check_cancelled();
        for (int c = 0; c < config.channels; ++c) {
            const auto channel = static_cast<std::size_t>(c);
            spectra[granule][channel] = banks[channel].process(
                lookahead.front()[channel],
                AnalysisBank::transient_between(lookahead.front()[channel], lookahead[1][channel]));
        }
        lookahead.pop_front();
        ++granule;
        if (granule == 2U) {
            writer.write_frame(spectra);
            granule = 0;
        }
    }
    void enqueue(Block block) {
        lookahead.push_back(std::move(block));
        if (lookahead.size() >= 2U) process_front();
    }
    void frame(double left, double right) {
        assembling[0][position] = left;
        if (config.channels == 2) assembling[1][position] = right;
        if (++position == 576U) {
            enqueue(std::move(assembling));
            assembling = Block{};
            position = 0;
        }
    }
    std::size_t validate_write(const std::uint8_t* data, std::size_t bytes) const {
        check_open();
        const auto frame_bytes = static_cast<std::size_t>(config.channels) * 2U;
        if (bytes % frame_bytes != 0U) throw std::invalid_argument("PCM block must contain complete interleaved frames");
        if (bytes != 0U && data == nullptr) throw std::invalid_argument("PCM pointer is null");
        const auto total = bytes / frame_bytes;
        if (total > std::numeric_limits<std::uint64_t>::max() - stats.input_frames)
            throw std::overflow_error("PCM frame counter overflow");
        return total;
    }
    void write(const std::uint8_t* data, std::size_t bytes) {
        const auto total = validate_write(data, bytes);
        const auto frame_bytes = static_cast<std::size_t>(config.channels) * 2U;
        std::array<std::array<double, 1024>, 2> input{};
        for (std::size_t first = 0; first < total;) {
            check_cancelled();
            const auto count = std::min<std::size_t>(1024U, total - first);
            for (std::size_t i = 0; i < count; ++i) {
                const auto* p = data + (first + i) * frame_bytes;
                input[0][i] = read_sample(p);
                if (config.channels == 2) input[1][i] = read_sample(p + 2);
            }
            stats.input_frames += static_cast<std::uint64_t>(count);
            if (config.input_sample_rate == 96000) {
                std::array<double,512> left{},right{};
                const auto left_count=decimators[0].push_into(input[0].data(),count,left.data(),left.size());
                const auto right_count=config.channels==2 ? decimators[1].push_into(input[1].data(),count,right.data(),right.size()) : 0;
                if (config.channels == 2 && left_count != right_count)
                    throw std::runtime_error("Resampler channel length mismatch");
                for (std::size_t i = 0; i < left_count; ++i)
                    frame(left[i], config.channels == 2 ? right[i] : 0.0);
            } else {
                for (std::size_t i = 0; i < count; ++i) frame(input[0][i], input[1][i]);
            }
            first += count;
        }
    }
    Stats finish() {
        if (state == State::Finished) return stats;
        check_open();
        if (stats.input_frames == 0U) throw std::runtime_error("Cannot finish empty PCM input");
        if (config.input_sample_rate == 96000) {
            const auto left = decimators[0].finish();
            const auto right = config.channels == 2 ? decimators[1].finish() : std::vector<double>{};
            if (config.channels == 2 && left.size() != right.size())
                throw std::runtime_error("Resampler tail length mismatch");
            for (std::size_t i = 0; i < left.size(); ++i)
                frame(left[i], config.channels == 2 ? right[i] : 0.0);
        }
        if (position != 0U) {
            enqueue(std::move(assembling));
            assembling = Block{};
            position = 0;
        }
        // Drain 1152 zero samples through the real analysis and hybrid banks.
        // The third block supplies lookahead and is emitted only if needed to
        // complete a two-granule MPEG frame. These are transform tails, not
        // replacement audio or independent fake silence frames.
        enqueue(Block{});
        enqueue(Block{});
        enqueue(Block{});
        if (granule != 0U) enqueue(Block{});
        // Very short valid Layer III streams can be misidentified as unrelated
        // formats by automatic probes. Seven physical frames provide enough
        // consecutive MPEG headers for reliable probing in the tested players.
        // Continue the real transform with zeros; never replace input audio.
        while (writer.frame_count() < 7U) {
            enqueue(Block{});
            enqueue(Block{});
        }
        lookahead.clear();
        writer.finish();
        check_cancelled();
        stats.output_bytes = writer.output_bytes();
        stats.encoded_mpeg_frames = writer.frame_count();
        stats.reconstructed_peak = writer.reconstruction_peak();
        stats.peak_protected_frames = writer.protected_frames();
        stats.minimum_peak_gain = writer.minimum_peak_gain();
        state = State::Finished;
        return stats;
    }
};

Encoder::Encoder(Config config, Sink sink) : impl_(std::make_unique<Impl>(config, std::move(sink))) {}
Encoder::~Encoder() = default;
void Encoder::write_pcm16le(const std::uint8_t* data, std::size_t bytes) {
    // Argument errors are recoverable only before any stream state changes.
    // A sink throwing invalid_argument mid-write is still a terminal failure.
    impl_->validate_write(data, bytes);
    try { impl_->write(data, bytes); }
    catch (...) { if (impl_->state == Impl::State::Open) impl_->state = Impl::State::Failed; throw; }
}
Stats Encoder::finish() {
    try { return impl_->finish(); }
    catch (...) { impl_->state = Impl::State::Failed; throw; }
}
void Encoder::request_cancel() noexcept { impl_->cancelled.store(true, std::memory_order_relaxed); }

} // namespace uwdev::mp3codec
