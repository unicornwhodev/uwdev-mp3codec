# Public Android API

Package: `dev.unicornwhodev.mp3codec`.

```kotlin
data class Mp3EncoderConfig(
    val inputSampleRate: Int,
    val channels: Int,
    val bitrateKbps: Int = 192
)
data class Mp3EncodingStats(
    val inputFrames: Long,
    val outputBytes: Long,
    val outputSampleRate: Int,
    val bitrateKbps: Int,
    val channels: Int,
    val encodedMpegFrames: Long
) {
    var peakProtection: Mp3PeakProtectionInfo? = null
        internal set
}
data class Mp3PeakProtectionInfo(
    val reconstructedTruePeak: Double,
    val protectedMpegFrames: Long,
    val minimumLinearGain: Double
)
// Created through Mp3Encoder.open(config, output).
// Implements AutoCloseable.
```

One PCM frame is one simultaneous sample from every input channel. It is
2 bytes for mono or 4 bytes for stereo; `inputFrames` never counts bytes or
individual interleaved channel values. `encodedMpegFrames` counts physical
1,152-sample MPEG frames, including required final drainage/padding.

## Lifecycle

| Operation | Contract |
| --- | --- |
| `open(config, output)` | Validate supported input rate, channels and bitrate before writing. Output remains owned by the caller. |
| `writePcm16Le(data, offset, length)` | Worker thread only; complete interleaved PCM frames; bounded streaming; zero length accepted. |
| `finish()` | Worker thread for the first call; drain filters/transforms/reservoir and cache statistics; empty input is an error. Repeated successful finish returns the same statistics. |
| `cancel()` | May be called from another thread; terminal cancellation; native resources released immediately when idle or on active-operation exit. |
| `close()` | Idempotent resource release. Unfinished input is discarded without implicitly finalizing. It never closes or flushes the caller's output. |

Writes after finish, cancellation or close are rejected. Simultaneous writes
or write/finish calls are rejected. A finish result already obtained remains
available after close; close does not invalidate cached immutable statistics.

Array bounds are checked using subtraction to avoid `offset + length`
integer overflow. Invalid array slices do not write output. PCM fragments
smaller than an interleaved frame are rejected; callers that receive arbitrary
byte fragments must assemble the last 0–3 bytes into a complete PCM frame.
Arbitrary **whole-frame** block sizes are internally accumulated into granules.

## Exceptions

All library exceptions derive from `Mp3EncoderException`:

* `Mp3ConfigurationException`: unsupported sample rate/channel count/bitrate.
* `Mp3InputException`: invalid slice or partial PCM frame.
* `Mp3EncodingException`: empty input or processing failure.
* `Mp3OutputException`: the caller's stream failed, with the original cause.
* `Mp3CancelledException`: observed cancellation.
* `Mp3NativeException`: library load, allocation or internal native failure.
* `Mp3StateException`: invalid lifecycle, concurrent producer or UI-thread use.

An output failure is terminal. Already-written bytes cannot be rolled back
by this API. Errors and cancellation release native resources through the
operation lease. Always use `use`/`try-with-resources` even when the caller
does not intend to finish.

## Safe output commit

For a user-visible file, write to a temporary destination, call `finish`,
close/flush the caller-owned output successfully, then rename or publish it.
Delete the temporary destination on failure if the caller owns it. Android
document providers may not support atomic rename; the application must make
that limitation explicit. The encoder does not manage URIs, the Storage
Access Framework, permissions or cleanup of caller-owned streams.

Input PCM is not globally normalized. The encoder reconstructs quantized
audio internally and applies linked channel gain on affected frames when its
documented 4x peak estimate would exceed 0.995. It retains one MPEG frame of
lookahead and fails the export if the bounded protection cannot converge.
`finish()` populates `peakProtection`; its six-argument statistics constructor
is preserved. These diagnostics describe internal estimates, not a universal
bound for every possible playback interpolation filter. See
[PEAK_PROTECTION.md](PEAK_PROTECTION.md) and
[RESULTATS_COURANTS.md](QUALIFICATION.md) for the verified behavior.
