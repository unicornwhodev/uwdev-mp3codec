# Architecture

The consumer renders its audio project to PCM16LE, opens a caller-owned output
stream, and supplies complete interleaved PCM frames. No DAW state, project
parser, network layer or storage permission handling is inside this library.

## Processing boundaries

1. **Kotlin API:** validate configuration and array slices, enforce lifecycle
   and worker-thread use, translate output failures, own the native session lease.
2. **JNI session:** transfer PCM through a bounded 32 KiB buffer, hold output
   and reusable output buffer references, invoke the Kotlin stream callback.
3. **PCM streaming:** decode signed little-endian samples in blocks of at most
   1,024 frames per channel and preserve sample order across arbitrary blocks.
4. **Resampling:** for 96 kHz only, run the original per-channel 192-tap FIR
   decimator; other supported rates bypass resampling.
5. **Analysis:** assemble 576-sample granules with one-granule lookahead,
   detect attacks, perform 32-band polyphase analysis and hybrid MDCT.
6. **Coding:** estimate permitted band distortion, optimize scale factors and
   global gain, select Huffman regions/codebooks, construct MPEG side information.
7. **Multiplexing:** pack main data into CBR physical frame slots, draw on a
   bounded 511-byte reservoir, emit completed frames incrementally.

`codec/` contains no JNI or Android dependencies. `jni/` contains no MPEG
algorithm. The host test harness compiles the identical codec sources used
in the AAR; it does not substitute an encoder.

## Ownership and concurrency

Each encoder owns its DSP history, lookahead, resampler, quantizer, pending
frames, counters and atomic cancellation flag. Immutable numeric constants
may be shared; there is no mutable global session registry. Concurrent
instances have independent state.

Kotlin permits one active write or finish operation per instance. A small
lock protects lifecycle and the native pointer, but is not held during
encoding or user `OutputStream.write`. `cancel()` marks the state and signals
the native atomic flag; the active operation releases the native object on
exit. When idle, cancellation destroys it immediately. This prevents both a
use-after-free and a lock that would keep cancellation waiting for a long encode.

A blocked, caller-defined `OutputStream.write` cannot be forcibly interrupted
by a generic stream API. Cancellation is observed after the callback returns.
The caller must choose an output with suitable blocking behavior.

## Memory and latency

Native PCM input staging, filter history, two-channel lookahead, quantizer
scratch space and the bit reservoir have sizes independent of song duration.
There is no mandatory complete PCM or complete MP3 allocation. The test
harness may retain short fixtures for comparison; that is outside production.

Transform delay, lookahead needed before emission, reservoir emission delay
and terminal sample padding are different quantities. `CODEC.md` documents
the sample timeline; `BENCHMARKS.md` records measured memory and throughput.
