# Changelog

## 0.3.0 - 2026-10-23

- Add an optional PCM/WAV export module pinned to the qualified 0.2.0 core binary.
- Assemble fragmented PCM into bounded blocks and validate RIFF/WAVE PCM16 chunks.
- Add background jobs, ordered/coalesced progress, cooperative cancellation and safe file commit.
- Supply Kotlin/Java examples and a complete Android file-picker/export/playback/save sample.
- Add local JVM, Android byte-equivalence, independent-decoder and Release/R8 sample checks.
- Keep the original core sources, AAR, native libraries and published artifacts unchanged.
- Distribute a complete SDK, standalone demo APK/project, original MIT WAV and English documentation through GitHub and npm.
- Keep npm core path/coordinate helpers compatible and add export, demo and example helpers.

## 0.2.0 - 2026-10-23

- Release the standalone Android PCM-to-MP3 library under the uwdev-mp3codec name.
- Preserve the public encoder/configuration/statistics/exception API during import migration.
- Add internal reconstructed-peak protection with linked stereo gain and bounded lookahead trials.
- Keep streaming buffers bounded, share immutable DSP/FIR tables and cache Huffman costs.
- Validate MPEG structure, decoded audio, lifecycle errors, cancellation, resource release,
  Android R8 consumers, sanitizers, three ABIs and actual 16 KiB page execution.
- Complete the 15-source, four-bitrate device corpus and accepted targeted listening.
- Ship an AAR, sources, Maven repository and npm artifact-location/integrity helpers.
- Supply English documentation and preserve MIT and third-party attribution notices.
