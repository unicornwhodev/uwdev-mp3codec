# Third-party notices

uwdev-mp3codec's original implementation is licensed under the MIT
license in `LICENSE`, copyright 2026 Unicorn Who Dev.

The production codec is an original PCM-to-MPEG-1 Layer III implementation.
No LAME, Shine, FFmpeg, libavcodec, libmp3lame, MediaCodec encoder, WASM codec,
remote service, or third-party encoder binary is incorporated.

Normative numerical data has these separately recorded sources:

* The MPEG polyphase window values in `codec/synthesis_window.hpp` come from
  `phoboslab/pl_mpeg` under MIT. Only numerical window data is incorporated;
  its decoder implementation is not incorporated. The original attribution
  and permission text are retained in `third-party-notices/pl_mpeg-MIT.txt`.
* Huffman code words, band boundaries and related format constants are
  reconstructed from numerical tables in `lieff/minimp3` under CC0-1.0.
  `docs/MPEG_SOURCES.md` records the immutable upstream source and generation
  procedure. Its decoder implementation is not linked into production.

The Gradle Wrapper is an Apache-2.0 build tool. The statically linked Android
C++ runtime has separate LLVM/Apache license notices. These notices are kept
in `third-party-notices/`; they are not relicensed as original MIT code.
The AAR bundles applicable notices in `META-INF/uwdev-mp3codec`.

FFmpeg and mpg123 are external validation tools only. Their libraries, source
code and executables are not included in the AAR. NumPy, SciPy, JUnit and
AndroidX Test are development/test dependencies only. Kotlin's standard
library is a transitive dependency of the Kotlin API with an Apache-2.0
artifact declaration and separately attributed BSD-3-Clause and BSL-1.0
portions. Its JVM runtime and JetBrains annotations provenance and relevant
notices are retained in `third-party-notices/KOTLIN-PROVENANCE.md` and the
adjacent license files. These dependencies are not merged into the AAR;
the sample APK packages the Kotlin JVM runtime.

ISO/IEC 11172-3 is the normative format reference. The protected text of the
standard is not redistributed. No ISO certification or definitive legal
opinion is asserted. See `docs/LICENSE_AUDIT.md` for the scoped provenance
review and `docs/VALIDATION.md` for the actual release status.
