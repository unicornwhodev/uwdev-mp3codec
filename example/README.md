# Encoding examples

`android` is a complete, independent Android Studio/Gradle application. It resolves
the facade 0.3.0 and qualified core 0.2.0 from `../../maven` relative to its root.
Use JDK 17 and Android SDK 36, then run `gradlew.bat :app:assembleRelease` on Windows
or `sh ./gradlew :app:assembleRelease` on Linux/macOS. No NDK or CMake is required.

`kotlin/EncodeWav.kt` and `java/EncodePcm.java` show minimal blocking calls for an
existing Android application. Run them on a worker thread. See `docs/EXPORT.md`
at the SDK/package root for background jobs, progress, cancellation and safe output.

The demo APK is in `demo` at the SDK/package root. It supports WAV selection,
a bundled original MIT sample, all four bitrates, playback and saving a copy.
Keep the root LICENSE, NOTICE.md and applicable third-party notices when copying.
