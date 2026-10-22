// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec

/** The bitrate is the total MPEG bitrate, including both stereo channels. */
data class Mp3EncoderConfig(
    val inputSampleRate: Int,
    val channels: Int,
    val bitrateKbps: Int = 192,
) {
    internal fun validate() {
        if (inputSampleRate !in setOf(44_100, 48_000, 96_000)) {
            throw Mp3ConfigurationException("Input sample rate must be 44100, 48000 or 96000 Hz")
        }
        if (channels != 1 && channels != 2) {
            throw Mp3ConfigurationException("Channels must be 1 or 2")
        }
        if (bitrateKbps !in setOf(128, 192, 256, 320)) {
            throw Mp3ConfigurationException("Bitrate must be 128, 192, 256 or 320 kbit/s")
        }
    }
}
