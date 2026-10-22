# Completed qualification for 0.2.0

The stable AAR is the same file used for the completed qualification. Its SHA-256
is `dc78b3b583abc95542f3d37487b2749670f75d58edbc26d00af5c342d2f574e4`.
See [the machine-readable summary](../qualification/summary.json) and
[ABI/ELF inspection](../qualification/aar-verification.json).

| Area | Executed result |
|---|---|
| Physical Android corpus | 15 sources at 4 CBR rates: 60 MP3 exports |
| Independent playback | Android, FFmpeg and mpg123 to end of stream |
| Structure and main data | 528 checks; 5 intentionally malformed controls rejected |
| DSP/signal matrix | 24 configurations, 264 signal cases |
| Edges and drainage | 204 cases |
| Native sanitizers | Windows ASan; Linux ASan and UBSan |
| Android runtime | ARM64 and ARM32 on Android 13; x86_64 on API 26 and API 35 |
| Page size | Actual 16 KiB API 35 emulator execution; 16 KiB ELF alignment |
| Minified consumer | Signed non-debuggable R8 Release export and Android playback |
| Independent Maven integration | Stable coordinate resolved by a separate project, built with R8 and run on API 26 |
| Listening | 8 selected required units accepted; 11 accepted passages from 10 MP3 files overall |

The device corpus is 48 kHz stereo PCM16LE with no automatic normalization.
The desktop reference uses FFmpeg/libmp3lame CBR at 128, 192, 256 and 320 kbit/s,
`compression_level=0`, `joint_stereo=0`, `abr=0`. It represents conventional
stereo, not LAME's usual joint-stereo setting. Comparison aligns encoder delay
and padding without fitting gain. Source, transfer and output hashes are checked.

Four of the eight files changed by peak protection were included in listening.
The remaining changed files passed the technical checks and have no invented
listening verdict. The accepted observations were labelled, not a controlled ABX
panel. Full-corpus perceptual equivalence to LAME and official ISO certification
are not claimed. All 60 outputs and all 528 extended cases retain technical checks.

## Reproduce numerical checks

Build `native-tests`, run CTest, then use `native-tests/verify_audio.py` and
`native-tests/verify_edges.py`. Those scripts require external FFmpeg, mpg123
and NumPy. `tools/audit_mp3_main_data.py` checks MPEG payload budgets and Huffman
syntax. `tools/verify_aar.py` checks native ABI, exports, runtime dependencies,
notices and ELF segment alignment. `tools/audit_source_licenses.py` inventories
source provenance and distributed artifacts.

Public reports contain aggregate results and artifact hashes. Raw workstation
logs, device identifiers, personal feedback transcripts and private history are
not distributed. Their omission does not turn an unperformed check into a pass.
