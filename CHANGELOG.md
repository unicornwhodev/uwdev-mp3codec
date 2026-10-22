# Changelog

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
