// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec

/** inputFrames counts interleaved PCM frames, not individual channel samples. */
data class Mp3EncodingStats(
    val inputFrames: Long,
    val outputBytes: Long,
    val outputSampleRate: Int,
    val bitrateKbps: Int,
    val channels: Int,
    val encodedMpegFrames: Long,
) {
    /** Populated by finish(); does not change the existing six-argument constructor. */
    var peakProtection: Mp3PeakProtectionInfo? = null
        internal set
}

/** Internal reconstruction estimate; external decoding remains the qualification oracle. */
data class Mp3PeakProtectionInfo(
    val reconstructedTruePeak: Double,
    val protectedMpegFrames: Long,
    val minimumLinearGain: Double,
)
