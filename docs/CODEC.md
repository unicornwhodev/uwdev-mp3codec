# Codec implementation

Android MP3 Encoder implements its own MPEG-1 Audio Layer III encoding path
in C++17. It consumes already rendered PCM. It does not interpret DAW
projects, mix tracks, call a platform encoder, or use an external MP3 engine.

The target syntax is ISO/IEC 11172-3. This document describes the implemented
algorithms and limits; it is not an ISO certification or a claim of perceptual
transparency. Numerical-data provenance is recorded in
[`DSP_SOURCES.md`](DSP_SOURCES.md) and [`MPEG_SOURCES.md`](MPEG_SOURCES.md).

## Supported formats

| Input PCM rate | MP3 rate | Channels | Total stream bitrate |
| --- | --- | --- | --- |
| 44,100 Hz | 44,100 Hz | 1 or 2 | 128, 192, 256 or 320 kbit/s |
| 48,000 Hz | 48,000 Hz | 1 or 2 | 128, 192, 256 or 320 kbit/s |
| 96,000 Hz | 48,000 Hz | 1 or 2 | 128, 192, 256 or 320 kbit/s |

These combinations form the 24-configuration public contract. The Kotlin
API's default bitrate is **192 kbit/s**. A stereo bitrate is the total
stream bitrate, not a separate bitrate for each channel.

Input samples are signed 16-bit little-endian integers, interleaved by
channel. Each API write must contain whole PCM frames: two bytes for mono,
four for stereo. Blocks may contain any number of whole frames, including
zero; the encoder buffers across writes until it has enough samples for a
granule. It does not require writes to align to 576- or 1152-frame boundaries.
Malformed partial PCM frames are rejected.

Output restrictions are explicit:

- MPEG-1 Layer III only; two granules of 576 samples per channel per frame.
- CBR only; no VBR or ABR.
- Ordinary mono or stereo; no joint stereo, mid/side or intensity stereo.
- No ID3, Xing/Info or gapless metadata.
- MPEG CRC disabled (`protection_bit = 1`).
- Emphasis, copyright and original bits are zero.

## Processing pipeline

### 1. PCM ingestion and per-session state

The byte reader reconstructs signed samples explicitly from little-endian
bytes, avoiding assumptions about pointer alignment. Samples are normalized
by 32768 before DSP processing. Input counters are 64-bit. The public encoder
uses bounded 1024-frame ingestion batches internally and accumulates
576-frame channel blocks.

Each session owns its filter histories, MDCT overlap, transient state,
resampler state, padding accumulator and reservoir queue. The only shared
codec data are immutable numerical tables. Multiple sessions are independent;
one session still requires a single producer, apart from its cancellation
signal.

### 2. Optional 96-to-48 kHz conversion

A 96 kHz source is filtered before decimation. Each channel uses a 192-tap,
symmetric low-pass FIR formed from a 22 kHz ideal-sinc response and a Kaiser
window with beta 8.6. Coefficients are normalized to unity DC gain. The
modified Bessel function used for the window is evaluated by a bounded,
convergent series.

The decimator keeps a fixed 192-sample ring buffer. Its output phase is the
even input-sample index: 0, 2, 4, and so on. Finalization sends 191 zeros
through the filter to retain the FIR tail.

Its linear-phase delay is **95.5 input samples**, equal to **47.75 samples at
48 kHz** (approximately 0.994792 ms). The half-sample fraction is real; it
must not be silently rounded away in fidelity comparisons. Tests construct
an independent filtered reference and compare the encoder against that
reference.

44.1 and 48 kHz sources bypass this filter. No other input rates are accepted.

### 3. Analysis filter bank

A 512-sample analysis history feeds a 32-band polyphase filter bank, advancing
by 32 PCM samples. The implementation uses a direct normalized transpose of
the standard synthesis matrix. It groups the eight 64-sample phases before
the cosine projection rather than applying a pre-existing encoder routine.

The standard numerical window originates from the permissively licensed
source identified in `DSP_SOURCES.md`. The production algorithm itself is
original to this repository. Eighteen filter-bank time slots form each
576-sample granule.

The alternating sign operation on odd subbands/odd time slots prepares the
subband samples for the Layer III hybrid representation.

### 4. Transient detection and hybrid MDCT

The encoder keeps one granule of source lookahead. Transient detection uses
short-window high-pass energy changes, with additional comparison across
adjacent granule boundaries. The block-state machine permits the required
normal → start → short → stop → normal sequence and remains on short blocks
when another transient requires it.

Long and transition blocks use a 36-sample MDCT window for 18 coefficients
per subband. Short blocks use three overlapping 12-sample windows, each
producing six coefficients. The normative start/stop windows bridge these
representations. Mixed blocks are not used in this version.

Before coding, long/transition coefficients undergo the inverse of the
decoder's orthogonal alias-reduction butterflies. Pure short blocks do not
use those butterflies. Short coefficients are then reordered from the DSP's
subband/frequency/window storage into the scalefactor-band/window/frequency
order required by the MPEG bitstream.

### 5. Psychoacoustic thresholds

The implemented model is deliberately modest. It estimates long-band power
and spectral flatness to distinguish concentrated tonal content from
noise-like content. Tonal bands receive stricter distortion thresholds.
Small asymmetric contributions from adjacent bands account for local
frequency masking, with a numerical noise floor.

For short blocks, each window/band uses its own spectral energy and spectral
concentration to choose a distortion threshold. These are actual
signal-dependent decisions. They are not a claim to implement ISO
psychoacoustic model 1 or model 2, nor a substitute for listening tests.

### 6. Quantization and distortion/rate loops

For `scalefac_scale = 0` and `preflag = 0`, candidate magnitudes reconstruct
according to:

```text
reconstructed = sign(q) * |q|^(4/3)
                * 2^((global_gain - 210)/4 - scalefactor/2)
```

The quantizer chooses the closest adjacent reconstructed magnitude. A
bounded search adjusts global gain to meet the bit budget. It also checks
nearby finer gains because a change of Huffman codebook can make bit use
locally nonmonotonic.

A distortion-control loop measures actual reconstruction error per
scalefactor band, compares it with the psychoacoustic threshold, refines
selected poorly masked bands, and reruns rate control. It retains the legal
candidate with the best normalized noise score. The loop has a fixed
iteration bound to prevent an unbounded export-time search.

Scalefactors are transmitted with a legal MPEG-1 compression selection.
The final implicit band has its normative zero scalefactor. Maximum
representable quantized magnitude is 8206, and every channel/granule's
`part2_3_length` is bounded to 4095 bits.

The frame allocator counts all nonzero spectral parts before dividing the
available bits. A part is silent for this purpose only if all 576
coefficients compare exactly equal to zero; there is no amplitude threshold
or gate for quiet audio. This prevents a later silent granule from reserving
bits that an earlier active granule needs. The additional operation is a
coefficient scan, not another quantization pass. The original bounded
quantization loops still run once per part. The regression and measured
effect on impulse quality are recorded in `BIT_ALLOCATION_REGRESSION.md`.

### 7. Entropy coding and bit accounting

Normal blocks search legal Huffman-region boundary combinations and choose
the least expensive usable pair table for each region. Switched blocks use
their normative two-region structure. The last region containing only zero
and one magnitudes uses the less expensive of the two count-one quadruple
tables. Trailing coefficients omitted from the bitstream are genuinely
quantized to zero.

All applicable Huffman codewords, escape linbits and sign bits are emitted
by this implementation. The generator and provenance for their normative
numeric data are documented in `MPEG_SOURCES.md`.

The candidate calculation counts every scalefactor, Huffman, linbit and sign
bit. Actual emission must match that count exactly. MPEG field writes also
reject values outside their encoded width. Forbidden table numbers 4 and 14
are never selected.

### 8. CBR framing and the bit reservoir

Frame byte sizes follow the MPEG-1 formula:

```text
base_frame_bytes = floor(144000 * bitrate_kbps / output_sample_rate)
frame_bytes      = base_frame_bytes + padding_bit
```

A per-session rational accumulator distributes padding bytes without
floating-point drift. Headers occupy four bytes; side information occupies
17 bytes in mono or 32 bytes in stereo. There is no CRC field.

The reservoir distinguishes physical frame payload positions from logical
compressed-audio positions. A frame may begin its logical data in unused
space in queued earlier frames. Its `main_data_begin` records that actual
backward distance. References cannot precede the stream or exceed 511 bytes.

Only finalized physical frames are emitted. Unused capacity older than the
reservoir limit becomes ancillary padding, keeping the queue bounded. The
bit reservoir works across writes; it is not recreated for each input block.
The encoder never stores the full PCM recording or completed MP3 internally.

## Delay, finalization and decoded length

Raw decoding of this implementation's untagged MP3 output has a
**1056-sample MPEG analysis/synthesis delay** at the output rate. This is
separate from lookahead/output-buffer latency and from the optional FIR
delay. At 96 kHz input, the original-source timing additionally includes
47.75 output samples of FIR delay. Comparing with a reference that already
includes the FIR response leaves the same 1056-sample MPEG alignment.

Let `Ninput` be the number of source PCM frames per channel. For a nonempty
source, define:

```text
Nresampled = Ninput                         for 44100 or 48000 Hz input
Nresampled = ceil((Ninput + 191) / 2)        for 96000 Hz input

MPEG_frames     = max(7, ceil(Nresampled / 1152) + 1)
decoded_samples = MPEG_frames * 1152        per channel
```

The count includes the causal FIR tail when used, the hybrid/filter-bank
drainage, final frame rounding, and a minimum of seven physical MPEG frames
for very short exports. The minimum addresses observed raw-format probing
ambiguity in independent players; the source samples are still processed by
the real encoding path. It adds terminal padding, not leading delay. See
[`SHORT_EXPORT_REGRESSION.md`](QUALIFICATION.md) for the initial
failures, investigation and completed regression tests.

At the minimum length, a decoded file contains 8064 samples per channel:
about 182.857 ms at 44.1 kHz, or 168 ms at 48 kHz. Empty input is rejected
rather than converted into such a file.

There are no gapless tags. This version therefore does not promise
sample-accurate file duration or automatic player trimming. `inputFrames`
and `encodedMpegFrames` let callers distinguish their source duration from
the physical MPEG duration. The library does not own or close the caller's
output stream.

## Practical limits and evidence

The documented format checks, independent decoding, sine SNR gate, edge
cases and measured audio results are recorded separately from Android
integration and device-performance evidence. Decodability is a structural
requirement; it does not establish perceptual transparency. Transient
pre-echo, quantization noise and near-full-scale reconstructed peaks remain
important review areas for this initial encoder. See `QUALITY_REVIEW.md`
and the final quality report for measurements and limitations.

The implementation uses floating-point DSP. For a given build, tests verify
the same output for the same PCM across different input block sizes.
Byte-identical output across
all CPU architectures or different system math-library versions is not
promised. Static numerical tables and filter construction have documented,
reproducible sources.
