# Source, dependency and distribution license audit

## Result and scope

The original encoder, JNI bridge, Kotlin API, sample implementation, test
programs and project documentation are supplied under the root MIT license,
copyright 2026 Unicorn Who Dev. The distribution also contains attributed
third-party numeric data, Gradle build infrastructure, and compiled runtime
components with their own notices. The MIT project license does not relicense
those components.

The optional export facade and the original bundled demonstration WAV/provenance
are also supplied under the project MIT license. The generator is included in the
SDK. Demo APK assets are compared byte for byte with the reviewed source assets;
the WAV has no external recording or sample dependency. AndroidX Test and Error
Prone annotations are test-only dependencies and are not included in the library
AARs or the standalone demo APK.

This is a source-specific technical provenance review. Its reproducible result
is `build/license-audit/report.json`; a release may copy that result to
`docs/results/license-audit.json`. The report lists each source file's path,
size, SHA-256, license class, applicable component licenses and provenance
explanation. It separately inventories every file entry in the release AAR,
its nested `classes.jar`, the sample APK, and the staged Maven sources JAR.
It also hashes the publication's POM, Gradle metadata and checksum files.

`PASS_SCOPED_CHECKS` means the recorded source/packaging checks passed for
those exact inputs. It is not a legal opinion, patent clearance, a finding
about every dependency available on the build machine, or ISO certification.
Any later source, notice, dependency or binary change requires a fresh run.
The report records the checked inputs instead of relying on a general claim
that an entire archive is "100% original MIT."

## File and component classification

| Actual files or payload | Classification | Evidence and retained notice |
|---|---|---|
| `encoder-android/src/main/cpp/codec/encoder.*`, `resampler.*`, public DSP/MPEG headers, JNI source and export map | Original implementation, MIT | Root `LICENSE`; no imported encoder implementation in these files |
| `codec/dsp.cpp`, `codec/mpeg.cpp`, `codec/huffman_tables.hpp` | Original MIT implementation/arrangement plus CC0-1.0 numerical data | Named numeric tables from pinned minimp3; `docs/MPEG_SOURCES.md`, `docs/DSP_SOURCES.md`, `third-party-notices/minimp3-CC0.txt` |
| `codec/synthesis_window.hpp` | Attributed MIT numerical data and original arrangement | 512 coefficients from pinned PL_MPEG; `third-party-notices/pl_mpeg-MIT.txt` |
| `encoder-android/src/main/kotlin/**`, `sample-app/src/main/**`, tests, generator, audit/verification scripts, CMake and Gradle configuration and project documents | Original project files, MIT | Root `LICENSE`; per-file manifest distinguishes exceptions |
| `gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar` | Third-party build infrastructure, Apache-2.0 | Unmodified Gradle 8.13 generated wrapper; original launcher headers, `Gradle-LICENSE.txt`, `Gradle-NOTICE.txt` |
| Native `libuwdev_mp3codec.so` for each of three ABIs | Compiled original code, attributed numeric tables, and statically linked LLVM C++ support | Original MIT and CC0 data provenance plus `Android-NDK-r27c-LLVM-NOTICE.txt`; runtime code is not claimed as original MIT |
| `org.jetbrains.kotlin:kotlin-stdlib:2.2.21` | Maven artifact declares Apache-2.0; relevant runtime portions additionally use BSD-3-Clause and BSL-1.0 | Kotlin copyright/Apache text and GWT, Guava, ThreeTenBP, Boost notices retained; `KOTLIN-PROVENANCE.md` |
| `org.jetbrains:annotations:13.0` | Apache-2.0, transitive Kotlin dependency | Upstream POM identifies JetBrains Team and Apache-2.0; metadata hashes in `KOTLIN-PROVENANCE.md` |
| `third-party-notices/*.txt` | Retained upstream license/attribution text | Each notice receives its own component classification and pinned SHA-256; none is relabeled as original MIT code |
| Generated test/measurement reports | Project-generated evidence | Original test data and analysis under project MIT; not the implementation of the tools used to produce them |

The complete file list is generated from the actual tree rather than repeated
manually here. It includes build scripts and source documents that are added
before a rerun. Unexpected binary files, unrecognized top-level source paths
and unclassified archive entries cause a review failure. Recognized source
directories use the project's authorship declaration, with explicit exceptions
for data-bearing files; this policy is not a plagiarism detector.

## Exact incorporated numerical material

### MPEG codewords and scalefactor constants

The upstream source is
[`lieff/minimp3` at `ea99364f61c14656440e8d77e9c233ccf3124633`](https://github.com/lieff/minimp3/tree/ea99364f61c14656440e8d77e9c233ccf3124633).
The source `minimp3.h` SHA-256 is
`57e437c5c1f0e8b243885d3929c8973b5e6c778451e0100ab4251d19915cb3ad`;
the retained upstream CC0 license SHA-256 is
`6a1ee543e5282cd9061881edf462e6fdab181f328da71fc2c9a6950a80e94d01`.

The original generator traverses the integer Huffman lookup representation
and emits codeword/length pairs. It also uses explicitly named numeric band
widths and scalefactor mapping values. It emits no upstream decoder functions,
control flow, SIMD implementation or binary. Regeneration from the pinned
input was byte-identical to `huffman_tables.hpp`, whose SHA-256 is
`1854ce07a3116771c9df0c1ceba74829615a09ba591268bfb3bb7966e6b3824d`.
The audit pins this generated header and the retained license. Further
derivation detail is in `MPEG_SOURCES.md`.

### Polyphase window

The numerical window comes from
[`phoboslab/pl_mpeg` at `c871f2be022ece7ef4f64230b4fb8e1fb9eb6023`](https://github.com/phoboslab/pl_mpeg/tree/c871f2be022ece7ef4f64230b4fb8e1fb9eb6023),
`pl_mpeg.h` Git blob `b42f53f89f868a697435ab1e15742f370819ffbc`.
Only `PLM_AUDIO_SYNTHESIS_WINDOW`'s 512 numerical values were extracted,
scaled to exact integer multiples of 1/65536 and arranged in the header.
The upstream file states MIT and attributes Dominic Szablewski without a
copyright year. The retained notice preserves those facts. The checked header
SHA-256 is `e9f8a5abb8203f742daea77ab6b4f32f5af2bdd7398e107fca97c3e24e2e9afd`.
No PL_MPEG decoder implementation is compiled into the encoder.

The analysis transform, MDCT implementation, FIR resampler, transient/masking
heuristics, quantization, reservoir and frame writer are original project
implementations. Their mathematical references and scaling conventions are
recorded in the DSP/MPEG source documents. The protected text of ISO/IEC
11172-3 is not distributed.

## Build tools and compiled runtime

The wrapper's Gradle distribution is 8.13. Its ZIP SHA-256,
`20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78`,
is recorded in `gradle-wrapper.properties` and was compared with the
[upstream distribution checksum](https://services.gradle.org/distributions/gradle-8.13-bin.zip.sha256).
The generated wrapper JAR SHA-256 is
`81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f`.
The audit also pins both launchers and the unchanged Gradle license/notice.
Gradle is source-distribution build infrastructure, not an Android encoder
runtime dependency.

The retained Gradle `LICENSE` and `NOTICE` are distribution-wide aggregates.
They also mention MIT/BSD and other licensed build dependencies, including
LGPL GNU Trove used by the Kotlin embeddable compiler. Retaining this upstream
notice text does not incorporate those implementations into the wrapper,
encoder or AAR. The Gradle distribution ZIP and its compiler/dependency JARs
are external build tools and are not redistributed here. The manifest marks
these notice files as aggregates rather than assigning every license named
inside them to the encoder.

`encoder-android/build.gradle.kts` explicitly selects Android NDK
`27.2.12479018` (r27c) and `ANDROID_STL=c++_static`. Consequently, the native
library contains compiled portions of libc++ and associated ABI/unwinding/
compiler support. The complete notice copied from the installed NDK's
`toolchains/llvm/prebuilt/linux-x86_64/NOTICE` has SHA-256
`f96f763beb66a7ba7a667647fc64c0226ace875e590c831fdd9579ec1c1d91e1`.
It retains Apache-2.0 with LLVM exceptions, legacy LLVM/libc++/libc++abi terms
and the upstream aggregate's other notices. Its text mentioning GPL
compatibility exceptions does not establish that GPL encoder code is linked.

The aggregate covers more toolchain components than this linker necessarily
selected. This audit preserves that full notice; it does not reconstruct a
license attribution for each object inside stripped ELF files. The binary
inspection reports `DT_NEEDED` dependencies, rejects unreviewed native
libraries, and scans for known external-codec signatures and network imports.
A static dependency cannot be ruled out solely by inspecting `DT_NEEDED`;
the source inventory and CMake dependency review are also part of the finding.

The built Maven POM exposes exactly
`org.jetbrains.kotlin:kotlin-stdlib:2.2.21`; Kotlin's own POM also exposes
JetBrains annotations 13.0. The library AAR's `classes.jar` contains the
project API and notices, with no merged Kotlin implementation classes. The
consumer resolves Kotlin through Maven, while the sample APK packages its
JVM runtime. Kotlin tag `v2.2.21` resolves to commit
`2146684dcba708e5a304758b41a9e4ec9c7eff71`. Its
[upstream license inventory](https://github.com/JetBrains/kotlin/blob/2146684dcba708e5a304758b41a9e4ec9c7eff71/license/README.md)
identifies the GWT/Guava Apache portions, ThreeTenBP time code under BSD and
Boost JVM math code under BSL-1.0. The relevant exact texts and copyright
attributions are included. See `third-party-notices/KOTLIN-PROVENANCE.md`
for the artifact hashes and source mapping.

Android Gradle plugin 8.11.1, Kotlin Gradle plugin 2.2.21, the Android SDK,
JDK 17, CMake and Ninja are external build tools. Their complete transitive
dependency graphs and installed SDK images are not redistributed or fully
audited by this report. A JDK/toolchain license therefore does not become a
license assigned to every original source file compiled by that toolchain.

## Production separation and network scope

The scan covers `encoder-android/src/main/**` and `sample-app/src/main/**`,
including the native CMake definition. It searches for known LAME, Shine,
FFmpeg/libavcodec, mpg123, MediaCodec-encoder and WebAssembly implementation
references, copyleft license markers, runtime network APIs and runtime URLs.
The Android XML schema namespace is not a network operation. Both production
manifests are parsed for permissions. The inspected sources declare no
network permission and contain no matched runtime network API or external
encoder implementation reference.

Gradle's Maven/Google/plugin repositories, wrapper download, source retrieval
for provenance and Maven publication are build-host network operations. They
are not runtime calls from the codec. The caller supplies PCM and an output
stream; processing itself has no server dependency. This review does not
make claims about an arbitrary application's own output-stream implementation
or a user's chosen document provider.

FFmpeg and mpg123 are external independent decoder tools used for validation.
Their executable files, libraries and source are not present in the reviewed
source/AAR/sample APK. Python test scripts that invoke those installed tools
remain original project scripts. NumPy/SciPy, JUnit and AndroidX Test are
development/test dependencies. Android tests may use platform MediaCodec as
a decoder; they are outside production source scope. An instrumentation APK
has additional test dependencies and is not the library's production runtime.

No known GPL, LGPL or AGPL encoder/decoder implementation is incorporated in
the reviewed production source or declared native dependencies. This is a
scoped finding based on inspected implementation/provenance and the recorded
checks. A successful keyword scan alone cannot prove originality, identify
all renamed code, establish third-party title or settle patent questions.

## Packaging checks and reproduction

The existing Gradle notice synchronization copies the root license, root
notice and complete `third-party-notices` directory into
`META-INF/android-mp3-encoder/`. The audit compares these files byte-for-byte
inside AAR `classes.jar`, the sample APK and the Maven sources JAR. The sources
JAR is also checked against every current Kotlin and native source file.
The root `LICENSE`, root `NOTICE.md` and complete third-party notice directory
are required in all three forms of Android distribution.

Run after all edits and after final Android packaging:

```sh
./gradlew :encoder-android:assembleRelease :sample-app:assembleDebug \
  :encoder-android:publishReleasePublicationToStagingRepository
python3 tools/audit_source_licenses.py
```

The Python tool requires Python 3.10 or later, the standard library and a
`readelf` executable. It performs no network requests and modifies no source
or packaged binary. The JSON is written atomically. A finding exits with
status 1 and lists the exact file/archive entry requiring review. Missing
artifacts also fail the full audit. To inspect source alone before an Android
build, explicitly use:

```sh
python3 tools/audit_source_licenses.py --source-only \
  --output build/license-audit/source-only.json
```

That reduced report clearly labels its scope and does not establish the
compiled-distribution checks. `--aar`, `--apk`, `--publication-dir` and
`--readelf` allow explicit artifact/tool locations.

Build output, tool caches and local machine configuration are excluded from
the source inventory. `docs/results/**` is identified as generated project
evidence but excluded from source hashing to avoid a self-referential audit
report. The final ZIP's separate `SHA256SUMS` covers those delivered reports
and binaries. Re-run the audit after a final documentation or notice change;
source hashes from a previous run are not a claim about modified files.
