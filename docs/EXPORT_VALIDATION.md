# Export facade validation

Stable export facade: `uwdev-mp3codec-export:0.3.0`, tested on 2026-10-23.
The qualified core remains `uwdev-mp3codec:0.2.0`, byte for byte.
Distribution version 0.3.0 adds the optional facade and SDK. No CI or GitHub workflow is used.

## Executed checks

| Check | Result |
|---|---|
| Frozen core AAR | Original SHA-256 preserved |
| Qualified production sources | All 21 manifest entries unchanged |
| Kotlin/Java JVM suite | 25 tests, zero failures/skips |
| Physical Android runtime | OPPO CPH2343, Android 13/API 33, ARM64 |
| Direct core vs fragmented PCM vs WAV | 24 configurations, all three routes byte-identical |
| Retrieved MP3 files | SHA-256 rechecked for all 72 files |
| Android decoder | 24 outputs decoded through end of stream |
| FFmpeg independent decoder | All 72 outputs decoded through end of stream |
| Android lifecycle | Background cancellation, executor delivery and main-thread rejection passed |
| Complete sample | Release/R8 export, playback, save-copy equality, cancellation cleanup and bundled WAV export passed |
| Independent Maven consumer | Java-only application resolved both AARs from local Maven, built Release/R8 and exported on OPPO |
| Native packaging | All three native libraries in the sample match the qualified AAR byte for byte |
| Additional native payload | Export AAR contains no native library |
| Packaged standalone demo | Built against the SDK's Maven files with normal R8, installed on OPPO, bundled WAV exported at 192 kbit/s and played to completion |

The qualified core AAR SHA-256 is:

```text
dc78b3b583abc95542f3d37487b2749670f75d58edbc26d00af5c342d2f574e4
```

The compatibility matrix covers 44.1/48/96 kHz, one/two channels and
128/192/256/320 kbit/s. It uses deterministic short signals with separate stereo
channel frequencies. Block boundaries differ from the direct call, and the WAV
fixtures include an odd-sized unknown chunk. This validates adapter transparency
for the executed cases, rather than claiming a new perceptual qualification.
The frozen core retains its [existing qualification and limits](QUALIFICATION.md).

The JVM suite additionally checks truncated/malformed WAV, unknown/trailing chunks,
byte fragments, exact declared PCM length, stream ownership, zero-read stalls,
early cancellation, cancellation during WAV parsing/write/finalization, destination
collisions, source-close/output-write failures, explicit overwrite, ordered/coalesced callbacks,
callback failures, Java checked-I/O factories and rejected worker executors.

The sample UI test uses local fixture documents to exercise the document-result
callbacks. Interactive system picker navigation and every external/cloud document
provider are not covered. The sample's provider cleanup limitation remains explicit.
The instrumented Release sample retains Kotlin runtime classes needed by the test
runner; application/facade/core code is processed by R8. A separate Java-only
consumer also passed normal Release/R8 without those test keep rules.

The facade runtime campaign was executed on ARM64/API 33. New ARM32, x86_64,
API 26 and 16 KiB facade runs were not performed. The native core's existing ABI,
API 26 and 16 KiB qualification is preserved by the unchanged binary.

## Evidence and reproduction

`python tools/validate_export.py --android-serial DEVICE_SERIAL` builds the
facade, runs the device campaign and saves machine-readable results and logs
under `build/export-validation`. Use `--offline` with populated Gradle caches.
Without an explicit Android target, its status identifies Android checks as pending.
Raw local evidence is ignored by Git and is not included in distribution archives.

`python tools/package_export.py` creates `build/release-0.3.0`, including a
combined Maven ZIP, separate AARs, English instructions, validation summary,
licenses and SHA-256 checksums. It selects only the stable 0.3.0 facade artifacts and the frozen 0.2.0 core,
excluding local SNAPSHOT builds. No credentials or device identifiers are bundled.
