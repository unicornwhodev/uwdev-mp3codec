# MPEG coding implementation and numerical-data provenance

This document records the sources for `codec/mpeg.cpp`,
`codec/huffman_tables.hpp`, and `scripts/generate_huffman_tables.py`.
The engine and generator were written for this repository. No MP3 encoder
implementation was incorporated. The distributed Android library does not
contain an external decoder or encoder.

## Normative format reference

The target format is **ISO/IEC 11172-3, MPEG-1 Audio Layer III**. The standard's
text is not included or redistributed. This project does not claim official
ISO certification. Successful decoding and the local structural checks are
implementation evidence, not a certification.

The required numerical codeword and scalefactor data are sourced from the
public-domain dedication of the upstream minimp3 decoder project:

- Project: <https://github.com/lieff/minimp3>
- Pinned revision: `ea99364f61c14656440e8d77e9c233ccf3124633`
- Numerical source: <https://github.com/lieff/minimp3/blob/ea99364f61c14656440e8d77e9c233ccf3124633/minimp3.h>
- Source `minimp3.h` SHA-256:
  `57e437c5c1f0e8b243885d3929c8973b5e6c778451e0100ab4251d19915cb3ad`
- Upstream license: **CC0 1.0 Universal**.
- License source: <https://github.com/lieff/minimp3/blob/ea99364f61c14656440e8d77e9c233ccf3124633/LICENSE>
- License-file SHA-256:
  `6a1ee543e5282cd9061881edf462e6fdab181f328da71fc2c9a6950a80e94d01`
- License copy: [`third-party-notices/minimp3-CC0.txt`](../third-party-notices/minimp3-CC0.txt).

The repository's MIT license applies to its original implementation and
arrangement. The incorporated numerical data retain their upstream CC0
provenance. This records a technical license review and is not a definitive
legal opinion.

## Exact incorporated data

| Production data | Upstream numerical source | Transformation |
| --- | --- | --- |
| Pair Huffman codewords | `tabs`, `tabindex`, `g_linbits` in `minimp3.h` | Traverse the integer lookup representation and emit `(codeword, length)` for each `(x, y)` symbol. |
| Count-one quadruple codewords | `tab32`, `tab33` | Enumerate the finite numerical lookup representation and emit the 16 codewords per table. |
| 44.1/48 kHz long-band boundaries | Rows 5 and 6 of `g_scf_long` | Cumulative sums of the 22 band widths. |
| 44.1/48 kHz short-band boundaries | Rows 5 and 6 of `g_scf_short` | One width per window, then cumulative sums of 13 frequency bands. |
| MPEG-1 scalefactor length choices | `g_scfc_decode` | Split each numerical entry into its two base-4 fields. |

The generator reads only the named integer initializers from the pinned
source file. It does not emit the source decoder's functions, control flow,
SIMD operations, or runtime data structures. The downloaded source itself is
not a production dependency and is not included in the AAR.

To reproduce the committed Huffman header, obtain the exact source above and
run from the repository root:

```sh
python3 scripts/generate_huffman_tables.py /path/to/minimp3.h
```

The generator rejects any source whose SHA-256 differs from the recorded
hash. It verifies symbol completeness, uniqueness, and the prefix property
for all 15 nonzero pair codebooks and both quadruple codebooks. Table zero is
the normative no-bit `(0, 0)` codebook. Forbidden table numbers 4 and 14 are
never selected. Tables 17–23 and 25–31 reuse their corresponding normative
base codeword table with the required different linbits counts.

## Original encoder decisions

### Quantization and rate control

The encoder reconstructs each candidate spectral magnitude using the actual
MPEG expression `|q|^(4/3) * 2^((global_gain-210)/4 - scalefactor/2)`.
It chooses the closest adjacent quantized magnitude, uses a bounded search
for a legal gain, and checks finer neighbouring gains because a Huffman size
can change nonmonotonically when symbols change.

Every candidate counts its actual scalefactor, pair-Huffman, linbits, sign,
and count-one bits before emission. A second count during emission must
match exactly. No granule/channel `part2_3_length` may exceed 4095 bits.
Pair magnitudes cannot exceed the representable maximum 8206.

The distortion-control loop computes actual squared reconstruction errors
per band. It compares their sums to the psychoacoustic threshold (the DSP
module reports a mean per-band threshold, so the coding stage multiplies
by the band's line count), selectively increases scalefactors in the worst
bands, then repeats rate control. It retains the legal candidate with the
lowest sum of `log(1 + noise / threshold)`.

This is a deliberately limited local optimization, not a claim to the
quality of mature encoders. Four outer iterations and three band refinements
per iteration bound its work. The short-block policy derives thresholds
from each window/band's own spectral energy and concentration.

### Huffman region selection

Normal blocks search all legal combinations of the two transmitted region
counts. Each region chooses the least expensive applicable pair codebook.
Switched blocks use the normative first 36-line region and the second
remaining region. Short MDCT coefficients are reordered from the DSP's
`subband * 18 + frequency * 3 + window` representation to scalefactor-band,
window, frequency order before quantization and coding.

The last all-small region uses the least expensive of count-one tables 32
and 33. Every trailing value not transmitted is genuinely quantized to zero;
no preselected test signal or synthetic replacement audio is used.

### Functional bit reservoir

Physical main-data capacity and logical audio-data positions are tracked
separately in 64-bit byte counters. A frame's `main_data_begin` is the number
of bytes between its physical main-data start and its already reserved
logical audio start in queued earlier frames.

An earlier frame is emitted only once all of its payload bytes can no
longer be changed. Unused space older than the 511-byte back-reference limit
becomes zero ancillary data. This caps the amount of delayed payload; there
is no storage proportional to the recording duration. Zero padding is added
only to byte-align a completed frame's logical data or fill unused CBR
ancillary capacity, never as a substitute for encoding input PCM.

The first frame cannot refer before the beginning of the stream. Every
encoded frame is checked against both the available physical capacity and
the individual 12-bit part-length limit. `finish()` emits the final queued
frames with their unused ancillary capacity filled.

### Scope and known limitations

CRC is disabled, copyright/original bits are zero, emphasis is none, and
channel mode is mono or ordinary stereo. There is no joint stereo, VBR,
ABR, ID3, or gapless tag. The reservoir and MDCT pipeline add bounded output
latency. The host tests report actual decoded delays and do not conceal them
with an unverified gapless claim.

Very short nonempty exports use a documented minimum of seven MPEG frames
to avoid ambiguous raw-format detection. This adds terminal padding only; see
[`SHORT_EXPORT_REGRESSION.md`](QUALIFICATION.md).

See `QUALITY.md` and the saved validation JSON for measured audio results.
A successful sine-wave test alone is not a perceptual-quality assessment.
