# Reconstructed-peak protection

Protection operates inside the encoder after quantization. Reference WAV files
and caller-supplied PCM are not globally normalized. Main comparisons preserve
their original levels.

The internal monitor reconstructs the actual quantized coefficients using
dequantization, short-band ordering, inverse alias reduction, IMDCT, overlap and
polyphase synthesis. It uses original equations and retains the existing MIT
attribution for the numerical synthesis window. It is not a public MP3 decoder
and does not add an external decoder dependency to the library.

The monitor takes the maximum reconstructed sample and a four-times interpolated
peak using an 81-tap Kaiser FIR, beta 5. The internal ceiling is **0.995 linear**.
This headroom covers the small numerical differences observed with independent
decoders; it is not a guarantee about every possible playback interpolation filter.

One actual MPEG frame is retained for lookahead: 24 ms at 48 kHz, about 26.1 ms at
44.1 kHz. Trial quantization works on copies of synthesis and reservoir state
before emitting bytes. If the peak exceeds the ceiling, bounded trials adjust
gain on the current and next frame. The same gain is used for both channels;
masking thresholds follow gain squared. Coefficients remain unchanged when the
predicted peak is within the ceiling.

Frames retain their audio content. Difficult passages are not replaced with
silent frames. An export fails if the bounded search cannot converge. Publish
the temporary output only after `finish()` succeeds and the output is closed.

`Mp3EncodingStats` keeps its public six-argument constructor. Its `peakProtection`
property reports the internal reconstructed peak, protected MPEG frame count and
minimum linear gain. External decoders are the independent qualification oracle.

The 60-file device corpus has no sample or documented four-times peak overload
after protection. Eight files changed; 52 remained byte-identical. Across 528
extended checks the largest measured sample peak was 0.9942087531 and the largest
four-times peak was 0.9948416317. Exact metrics and scope are recorded in the
[qualification summary](../qualification/summary.json).

The worst measured SNR cost on the corrected corpus was about 1.836 dB. A lower
waveform SNR by itself does not establish an audible degradation. Targeted labelled
listening was accepted; universal transparency or full-corpus LAME equivalence
has not been inferred from those observations.
