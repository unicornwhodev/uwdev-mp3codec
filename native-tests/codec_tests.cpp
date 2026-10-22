// SPDX-License-Identifier: MIT
#include "codec/encoder.hpp"
#include "codec/mpeg.hpp"
#include "codec/resampler.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

namespace {
void require(bool ok, const char* what) { if (!ok) throw std::runtime_error(what); }
template<class E, class F> void fails(F f, const char* what) {
    bool thrown = false;
    try { f(); } catch (const E&) { thrown = true; }
    require(thrown, what);
}
std::vector<std::uint8_t> tone(std::size_t frames, int channels = 1) {
    std::vector<std::uint8_t> bytes(frames * static_cast<std::size_t>(channels) * 2U);
    for (std::size_t i = 0; i < frames; ++i) {
        for (int c = 0; c < channels; ++c) {
            const auto s = static_cast<std::int16_t>(std::lround(12000 * std::sin(6.283185307179586 * (997 + c * 153) * static_cast<double>(i) / 44100)));
            const auto u = static_cast<std::uint16_t>(s);
            const auto p = (i * static_cast<std::size_t>(channels) + static_cast<std::size_t>(c)) * 2U;
            bytes[p] = static_cast<std::uint8_t>(u & 255U);
            bytes[p + 1] = static_cast<std::uint8_t>(u >> 8U);
        }
    }
    return bytes;
}
std::vector<std::uint8_t> encode(const std::vector<std::uint8_t>& pcm, std::size_t chunk_frames, int channels = 1, int rate = 44100) {
    std::vector<std::uint8_t> result;
    uwdev::mp3codec::Encoder e({rate, channels, 192}, [&](const std::uint8_t* p, std::size_t n) { result.insert(result.end(), p, p+n); });
    e.write_pcm16le(nullptr, 0);
    const auto chunk_bytes = chunk_frames * static_cast<std::size_t>(channels) * 2U;
    for (std::size_t p = 0; p < pcm.size();) {
        const auto n = std::min(chunk_bytes, pcm.size() - p);
        e.write_pcm16le(pcm.data() + p, n);
        p += n;
    }
    const auto a = e.finish();
    const auto b = e.finish();
    require(a.input_frames == pcm.size() / (static_cast<std::size_t>(channels) * 2U), "input frame statistics");
    require(a.output_bytes == result.size() && b.output_bytes == a.output_bytes, "output statistics/idempotent finish");
    fails<std::runtime_error>([&] { e.write_pcm16le(nullptr, 0); }, "write after finish must fail");
    require(e.finish().output_bytes == a.output_bytes, "invalid post-finish write must not invalidate completed statistics");
    return result;
}

void check_silent_granule_allocation() {
    // A nonzero granule must receive the same coding budget whether the
    // exactly silent granule comes before or after it. Check the emitted main
    // data, independently of the allocator's internal counters or decisions.
    for (const int rate : {44100, 48000}) {
        for (const int channels : {1, 2}) {
            auto at = [=](std::size_t active_granule) {
                std::array<std::array<uwdev::mp3codec::Spectrum, 2>, 2> frame{};
                for (int c = 0; c < channels; ++c) {
                    auto& spectrum = frame[active_granule][static_cast<std::size_t>(c)];
                    spectrum.masking.fill(1e-12);
                    for (std::size_t k = 0; k < spectrum.values.size(); ++k) {
                        spectrum.values[k] = 0.002 * std::sin(0.71 * static_cast<double>(k + 1U))
                                           + 0.001 * std::cos(0.37 * static_cast<double>(k + 3U));
                    }
                }
                std::vector<std::uint8_t> result;
                uwdev::mp3codec::MpegWriter writer(rate, channels, 192,
                    [&](const std::uint8_t* p, std::size_t n) { result.insert(result.end(), p, p+n); });
                writer.write_frame(frame);
                writer.finish();
                return result;
            };
            const auto first = at(0);
            const auto second = at(1);
            const std::size_t prefix = channels == 1 ? 21U : 36U;
            require(first.size() == second.size() && first.size() > prefix, "granule-order frame lengths");
            require(std::any_of(first.begin() + static_cast<std::ptrdiff_t>(prefix), first.end(),
                                [](std::uint8_t byte) { return byte != 0U; }), "active granule has nonzero main data");
            require(std::equal(first.begin() + static_cast<std::ptrdiff_t>(prefix), first.end(),
                               second.begin() + static_cast<std::ptrdiff_t>(prefix)),
                    "later silent granule must not reserve an unused audio budget");
        }
    }
}
}

int main() {
    try {
        check_silent_granule_allocation();
        const auto discard = [](const std::uint8_t*, std::size_t) {};
        for (auto c : {uwdev::mp3codec::Config{22050,1,192}, {44100,0,192}, {44100,3,192}, {44100,1,64}})
            fails<std::invalid_argument>([&] { uwdev::mp3codec::Encoder e(c, discard); }, "invalid config");
        fails<std::invalid_argument>([&] { uwdev::mp3codec::Encoder e({44100,1,192}, {}); }, "null sink");
        {
            uwdev::mp3codec::Encoder e({44100,1,192}, discard);
            fails<std::runtime_error>([&] { e.finish(); }, "empty input");
        }
        {
            uwdev::mp3codec::Encoder e({44100,2,192}, discard);
            std::uint8_t sample[4]{};
            fails<std::invalid_argument>([&] { e.write_pcm16le(sample, 2); }, "partial stereo frame");
            fails<std::invalid_argument>([&] { e.write_pcm16le(nullptr, 4); }, "null PCM");
            e.write_pcm16le(sample, 4);
            require(e.finish().input_frames == 1U, "recover after bad argument");
        }
        {
            uwdev::mp3codec::Encoder e({44100,1,192}, discard);
            e.request_cancel();
            fails<uwdev::mp3codec::Cancelled>([&] { e.write_pcm16le(nullptr, 0); }, "cancel before input");
        }
        {
            const auto pcm = tone(8192);
            uwdev::mp3codec::Encoder e({44100,1,192}, [](const std::uint8_t*, std::size_t) { throw std::runtime_error("sink failure"); });
            fails<std::runtime_error>([&] { e.write_pcm16le(pcm.data(), pcm.size()); e.finish(); }, "sink failure");
            fails<std::runtime_error>([&] { e.finish(); }, "failed session remains terminal");
        }
        {
            const auto pcm = tone(8192);
            uwdev::mp3codec::Encoder e({44100,1,192}, [](const std::uint8_t*, std::size_t) { throw std::invalid_argument("caller sink failed"); });
            fails<std::invalid_argument>([&] { e.write_pcm16le(pcm.data(), pcm.size()); e.finish(); }, "sink invalid_argument propagation");
            fails<std::runtime_error>([&] { e.write_pcm16le(nullptr, 0); }, "sink argument exception must still make session terminal");
        }
        for (const int rate : {44100, 48000, 96000}) {
            const auto pcm = tone(10031, 2);
            const auto whole = encode(pcm, 20000, 2, rate);
            require(!whole.empty(), "nonempty encoding");
            require(whole == encode(pcm, 1, 2, rate), "one-frame chunk determinism");
            require(whole == encode(pcm, 4096, 2, rate), "4096-frame chunk determinism");
            require(whole == encode(pcm, 137, 2, rate), "arbitrary chunk determinism");
        }
        for (std::size_t n : {1U, 7U, 575U, 576U, 577U, 1151U, 1152U, 1153U})
            require(!encode(tone(n), 1).empty(), "short source encoding");
        {
            const auto pcm = tone(4096);
            std::array<std::vector<std::uint8_t>, 4> results;
            std::array<std::exception_ptr, 4> errors{};
            std::vector<std::thread> workers;
            for (std::size_t i = 0; i < results.size(); ++i) workers.emplace_back([&, i] {
                try { results[i] = encode(pcm, 1 + i*73); } catch (...) { errors[i] = std::current_exception(); }
            });
            for (auto& worker : workers) worker.join();
            for (std::size_t i = 0; i < results.size(); ++i) {
                if (errors[i]) std::rethrow_exception(errors[i]);
                require(results[0] == results[i], "simultaneous instance independence");
            }
        }
        {
            std::atomic<bool> entered{false};
            std::atomic<bool> caught{false};
            std::exception_ptr error;
            const auto pcm = tone(8192);
            uwdev::mp3codec::Encoder e({44100,1,192}, [&](const std::uint8_t*, std::size_t) { entered.store(true); });
            std::thread producer([&] {
                try { for (;;) e.write_pcm16le(pcm.data(), pcm.size()); }
                catch (const uwdev::mp3codec::Cancelled&) { caught.store(true); }
                catch (...) { error = std::current_exception(); entered.store(true); }
            });
            while (!entered.load()) std::this_thread::yield();
            e.request_cancel();
            producer.join();
            if (error) std::rethrow_exception(error);
            require(caught.load(), "cross-thread cancellation");
        }
        for (int i = 0; i < 40; ++i) {
            const auto pcm = tone(600);
            uwdev::mp3codec::Encoder e({44100,1,192}, discard);
            e.write_pcm16le(pcm.data(), pcm.size());
            if (i % 2 == 0) e.finish(); // alternating normal finalization and premature destruction
        }
        std::cout << "PASS silent-granule allocation, native API, lifecycle, chunking, concurrent instances, cancellation and repeated destruction\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "FAIL " << e.what() << '\n';
        return 1;
    }
}
