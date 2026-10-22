// SPDX-License-Identifier: MIT
// Host-only validation driver; not distributed in the Android AAR.
#include "codec/encoder.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
#if defined(__unix__)
#include <sys/resource.h>
#endif

namespace {
struct PendingOutput {
    std::filesystem::path path;
    ~PendingOutput() {
        if (!path.empty()) {
            std::error_code ignored;
            std::filesystem::remove(path, ignored);
        }
    }
};
int integer(const char* text, int lo, int hi) {
    std::size_t pos = 0;
    const std::string value(text);
    const long v = std::stol(value, &pos);
    if (pos != value.size() || v < lo || v > hi) throw std::invalid_argument("Invalid integer argument");
    return static_cast<int>(v);
}
}

int main(int argc, char** argv) {
    try {
        if (argc < 6 || argc > 8) {
            std::cerr << "usage: mp3_encode input.pcm output.mp3 sampleRate channels kbps [blockFrames]\n"
                         "   or: mp3_encode --sine output.mp3 sampleRate channels kbps blockFrames seconds\n";
            return 2;
        }
        const int rate = integer(argv[3], 1, 192000);
        const int channels = integer(argv[4], 1, 2);
        const int bitrate = integer(argv[5], 1, 320);
        const int block = argc > 6 ? integer(argv[6], 1, 65536) : 4096;
        const bool generate = std::string(argv[1]) == "--sine";
        if (generate && argc != 8) throw std::invalid_argument("Generated sine requires seconds");
        if (!generate && argc == 8) throw std::invalid_argument("Unexpected argument");
        const int seconds = generate ? integer(argv[7], 1, 36000) : 0;
        std::ifstream input;
        if (!generate) {
            input.open(argv[1], std::ios::binary);
            if (!input) throw std::runtime_error("Cannot open input PCM");
        }
        PendingOutput pending{std::filesystem::path(std::string(argv[2]) + ".part")};
        std::ofstream output(pending.path, std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("Cannot open test output");
        const auto start = std::chrono::steady_clock::now();
        uwdev::mp3codec::Encoder encoder({rate, channels, bitrate}, [&](const std::uint8_t* data, std::size_t n) {
            output.write(reinterpret_cast<const char*>(data), static_cast<std::streamsize>(n));
            if (!output) throw std::runtime_error("Test output write failed");
        });
        std::vector<std::uint8_t> buffer(static_cast<std::size_t>(block * channels * 2));
        if (generate) {
            const auto count = static_cast<std::uint64_t>(rate) * static_cast<std::uint64_t>(seconds);
            for (std::uint64_t first = 0; first < count;) {
                const auto frames = std::min<std::uint64_t>(static_cast<std::uint64_t>(block), count - first);
                for (std::uint64_t i = 0; i < frames; ++i) {
                    for (int c = 0; c < channels; ++c) {
                        const double f = c == 0 ? 1000.0 : 733.0;
                        const double phase = 6.2831853071795864769 * f * static_cast<double>(first + i) / rate;
                        const auto sample = static_cast<std::int16_t>(std::lround(16383.0 * std::sin(phase)));
                        const auto u = static_cast<std::uint16_t>(sample);
                        const auto k = (static_cast<std::size_t>(i) * static_cast<std::size_t>(channels) + static_cast<std::size_t>(c)) * 2U;
                        buffer[k] = static_cast<std::uint8_t>(u & 255U);
                        buffer[k+1] = static_cast<std::uint8_t>(u >> 8U);
                    }
                }
                encoder.write_pcm16le(buffer.data(), static_cast<std::size_t>(frames) * static_cast<std::size_t>(channels) * 2U);
                first += frames;
            }
        } else {
            while (input) {
                input.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(buffer.size()));
                const auto n = input.gcount();
                if (n > 0) encoder.write_pcm16le(buffer.data(), static_cast<std::size_t>(n));
            }
            if (!input.eof()) throw std::runtime_error("Test input read failed");
        }
        const auto stats = encoder.finish();
        output.flush();
        if (!output) throw std::runtime_error("Test output flush failed");
        output.close();
        if (!output) throw std::runtime_error("Test output close failed");
        std::filesystem::rename(pending.path, std::filesystem::path(argv[2]));
        pending.path.clear();
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        long peak_kib = -1;
        long process_vm_hwm_kib = -1;
        double cpu_seconds = -1;
#if defined(__unix__)
        struct rusage usage {};
        if (getrusage(RUSAGE_SELF, &usage) == 0) {
            peak_kib = usage.ru_maxrss;
            cpu_seconds = usage.ru_utime.tv_sec + usage.ru_utime.tv_usec * 1e-6 + usage.ru_stime.tv_sec + usage.ru_stime.tv_usec * 1e-6;
        }
#endif
#if defined(__linux__)
        // Unlike getrusage's inherited pre-exec high-water history, VmHWM is
        // scoped to this executable's address space. Both values are reported.
        std::ifstream status("/proc/self/status");
        std::string status_line;
        while (std::getline(status, status_line)) {
            if (status_line.rfind("VmHWM:", 0) == 0) {
                process_vm_hwm_kib = std::stol(status_line.substr(6));
                break;
            }
        }
#endif
        std::cout << "{\"input_frames\":" << stats.input_frames
                  << ",\"output_bytes\":" << stats.output_bytes
                  << ",\"encoded_mpeg_frames\":" << stats.encoded_mpeg_frames
                  << ",\"output_sample_rate\":" << stats.output_sample_rate
                  << ",\"channels\":" << stats.channels
                  << ",\"bitrate_kbps\":" << stats.bitrate_kbps
                  << ",\"reconstructed_peak\":" << stats.reconstructed_peak
                  << ",\"peak_protected_frames\":" << stats.peak_protected_frames
                  << ",\"minimum_peak_gain\":" << stats.minimum_peak_gain
                  << ",\"wall_seconds\":" << elapsed
                  << ",\"cpu_seconds\":" << cpu_seconds
                  << ",\"process_peak_rss_kib\":" << peak_kib
                  << ",\"process_vm_hwm_kib\":" << process_vm_hwm_kib
                  << ",\"audio_seconds\":" << static_cast<double>(stats.input_frames) / rate
                  << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "encode error: " << error.what() << '\n';
        return 1;
    }
}
