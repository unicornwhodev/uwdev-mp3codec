# DSP design and provenance

## Sources and incorporated material

The implementation in `codec/dsp.cpp`, `codec/resampler.cpp` and the internal
reconstruction monitor in `codec/synthesis.cpp` is original
code written for this project. No existing MP3 encoder is called or wrapped.

The MPEG technical reference is ISO/IEC 11172-3. No text or pages from that
standard are distributed. The publicly accessible explanation by Martin
Sieler and Ralph Sperschneider, *MPEG-Layer3 Bitstream Syntax and Decoding*,
issue 1.2, 1997-03-04, was consulted for the mathematical decoder contract:

https://mp3guessenc.sourceforge.io/MPEG%20Layer3%20Bitstream%20Syntax%20and%20Decoding.pdf

Only the following externally sourced numeric data are incorporated:

| Data | Source and revision | Distribution basis |
|---|---|---|
| 512 synthesis-window values in `synthesis_window.hpp` | `phoboslab/pl_mpeg`, `pl_mpeg.h`, commit `c871f2be022ece7ef4f64230b4fb8e1fb9eb6023`, Git blob `b42f53f89f868a697435ab1e15742f370819ffbc` | Upstream SPDX MIT; retained author attribution and terms in `third-party-notices/pl_mpeg-MIT.txt` |
| Long scalefactor-band boundaries for 44.1 and 48 kHz | Numeric cumulative sums of `g_scf_long` rows 5 and 6 in `lieff/minimp3`, commit `ea99364f61c14656440e8d77e9c233ccf3124633` | Upstream CC0; see `third-party-notices/minimp3-CC0.txt` |
| Eight alias-butterfly parameters | MPEG mathematical constants `[-.6,-.535,-.33,-.185,-.095,-.041,-.0142,-.0037]`, checked against the technical reference and CC0 minimp3 decoder numeric constants | Functional mathematical parameters; no copied implementation |

The PL_MPEG values were multiplied by two to form integers; dividing these
integers by 65536 restores the standardized normalized synthesis window.
Only the numerical array was extracted. Neither PL_MPEG executable code nor
its audio/video decoder is compiled into this project. The file at the pinned
revision explicitly says `SPDX-License-Identifier: MIT` and attributes Dominic
Szablewski; it does not supply a copyright year. We retain those facts without
inventing a year. Standard MIT terms are included as the meaning of the SPDX
identifier: https://spdx.org/licenses/MIT.html .

This provenance review is technical evidence, not a legal opinion or a
certification of ISO conformity.

## Original polyphase analysis derivation

Let `D[n]` be the normalized synthesis window, `m=floor(n/32)`, `j=n mod 32`,
and `k` a subband index. Expanding the standardized synthesis matrix and its
interleaved FIFO selection gives the synthesis impulse response

```
H[k,n] = D[n] cos(pi/64 * (2k+1) * (16+32(m mod 2)+j)).
```

The matched analysis bank is its transpose with normalization `1/32`. It
uses a causal 512-sample chronological history ending with the newest
32 samples. Eight polyphase terms share the same cosine, so the code first
adds the 8 terms for each `n mod 64`, then applies the 32-by-64 cosine matrix.
This is an original direct derivation; it is not an adaptation of an encoder
implementation. No mutable matrix or history is shared between sessions.

The approximate perfect-reconstruction polyphase pair introduces 480 PCM
samples of delay with this chosen phase convention. Its small reconstruction
error is inherent to the windowed pseudo-QMF bank. A numerical random-noise
roundtrip against the independent synthesis equations measured about 84.4 dB
SNR and unity gain before quantization; it does not by itself measure MP3
quality or establish correct bitstream coding.

## Hybrid transform and block decisions

Each of the 32 bands stores 18 previous samples. Odd time slots in odd
subbands are inverted before the hybrid transform. Long windows transform
36 samples to 18 coefficients, with forward normalization `2/18`. Short
windows transform three overlapping sets of 12 samples to 6 coefficients
each, with normalization `2/6`. Those normalizations are the counterparts of
the unnormalized MPEG inverse transform.

The output convention is normalized PCM: reconstruction is
`sign(q)*abs(q)^(4/3)*2^((global_gain-210)/4-scalefactor/2)` when
`scalefac_scale=0`. Long coefficients are stored at `18*subband+frequency`;
short coefficients at `18*subband+3*frequency+window`. The MPEG writer reorders
short data by scalefactor band, window, then frequency before Huffman coding.

Long/start/stop coefficients undergo the inverse decoder alias butterflies.
Pure short blocks do not. The block-state transitions are normal to start,
start to short, short to short or stop, and stop to normal or start.
Lookahead uses energy jumps in 64-sample derivative-emphasized segments and
across adjacent granule boundaries. The hybrid pair adds 576 samples of
delay, making the unquantized full-bank reconstruction delay 1056 samples.
MP3 frame completion and any decoder-specific handling are additional
reasons to measure actual decoded alignment rather than promise gapless
audio. Transient heuristics are simple and are not an ISO psychoacoustic
model implementation.

The masking estimator measures power and spectral flatness in real
scalefactor bands. Tonal bands request a smaller error than noise-like bands;
limited asymmetric spreading allows neighboring bands to contribute. The
returned thresholds are **mean noise power per line**. The quantizer must
multiply by the number of lines when comparing a sum of squared errors.
These conservative heuristics do not establish perceptual transparency.

## 96 kHz decimation

The decimator generates a 192-tap symmetric FIR from the sinc formula at
22000/96000 cycles per input sample and a Kaiser window with beta 8.6.
The modified Bessel function is evaluated by a bounded convergent series.
The taps are normalized to unity DC gain. No external DSP table is used.

The causal filter has 95.5 input samples of group delay, corresponding to
47.75 output samples, or about 0.994792 ms. The first output is at input time
zero; subsequent outputs are at input times 2, 4, and so forth. `finish()`
feeds 191 zeros, preserving the complete finite filter tail. Total output
samples for a nonempty input of N samples are `ceil((N+191)/2)`. Finalization
of an empty resampler returns no data. Repeated resampler finalization returns
no additional data. The encoder separately rejects an empty input stream.

Analytical response measured from the generated coefficients on the host:

| Frequency | Amplitude response |
|---|---:|
| 1 kHz | -0.000000068 dB |
| 10 kHz | -0.00000726 dB |
| 20 kHz | +0.000299 dB |
| 21 kHz | -0.0983 dB |
| 22 kHz | -6.0206 dB |
| 24 kHz | -89.7003 dB |
| 26 kHz | -108.6716 dB |

The coefficient centroid was 95.50000000000004 and the sum was
1.0000000000000002 in the host double-precision calculation. This is an
algorithm check, not a physical Android-device performance measurement.
