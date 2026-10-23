# uwdev-mp3codec

**Stable Android PCM/WAV-to-MP3 export SDK, version 0.3.0.**

The optional export facade is version **0.3.0**. It uses the exact qualified
**0.2.0** core AAR, with unchanged native libraries and audio encoding behavior.
The SDK includes English documentation, Java/Kotlin examples and a complete
Android demo with file selection, progress, cancellation, playback and save-copy.

Encode interleaved PCM16LE into MPEG-1 Layer III locally on Android. The library
includes its own C++ encoder, a Kotlin API, streaming output, cancellation and
reconstructed-peak protection. No external encoder or network service is used.

| Contract | Supported values |
|---|---|
| Android | API 26 and later |
| Native ABI | arm64-v8a, armeabi-v7a, x86_64 |
| PCM input | Signed 16-bit little-endian, mono or stereo |
| Input sample rate | 44,100 / 48,000 / 96,000 Hz |
| MP3 output | CBR 128 / 192 / 256 / 320 kbit/s |
| Resampling | 96 kHz input is filtered and converted to 48 kHz |
| Kotlin package | `dev.unicornwhodev.mp3codec` |
| Maven coordinate | `io.github.unicornwhodev:uwdev-mp3codec:0.2.0` |
| Export facade | `io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0` |

## Try the complete demo

Download the [0.3.0 SDK and demo APK](https://github.com/unicornwhodev/uwdev-mp3codec/releases/tag/v0.3.0).
Install the demo on Android 8/API 26 or later, tap **Use bundled WAV sample**,
choose a bitrate and tap **Export MP3**. Play or save a copy after completion,
or choose your own PCM16 WAV. The original two-second sample is included under MIT.

The SDK ZIP contains both AARs, a local Maven repository, documentation, checksums
and a standalone Android Studio project. The same demo, project and documentation
are included in the npm package. The APK is a non-debuggable R8 Release signed
locally with an Android debug key; no signing key is distributed.

## Install with Gradle

Add the public, version-pinned Maven repository in `settings.gradle.kts`:

```kotlin
dependencyResolutionManagement {
    repositories {
        maven { url = uri("https://raw.githubusercontent.com/unicornwhodev/uwdev-mp3codec/v0.3.0/maven") }
        google()
        mavenCentral()
    }
}
```

Then add the dependency to your Android module:

```kotlin
dependencies {
    implementation("io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0")
}
```

This resolves the frozen core transitively. Consumers do not need an NDK or CMake.
For low-level PCM-only integration, use `uwdev-mp3codec:0.2.0` directly.
See the [export guide](docs/EXPORT.md) for complete asynchronous examples and
the [integration guide](docs/INTEGRATION.md) for offline/direct AAR installation.

## Use the Android encoder

For WAV/PCM files, background jobs, progress and cancellation, the optional
[export facade](docs/EXPORT.md) provides a complete integration and Android sample.
Its stable `0.3.0` artifact depends on the exact qualified `0.2.0` binary.
The existing low-level API below remains available unchanged.

```kotlin
// Blocking call: run on a worker thread. The destination must not already exist.
val result = dev.unicornwhodev.mp3codec.export.Mp3Export.fromWav(
    sourceWav, destinationMp3,
    dev.unicornwhodev.mp3codec.export.Mp3Preset.HIGH_256,
)
```

Run encoding on a worker thread. Each PCM block must contain complete channel frames.

```kotlin
import dev.unicornwhodev.mp3codec.Mp3Encoder
import dev.unicornwhodev.mp3codec.Mp3EncoderConfig

outputStream.use { output ->
    Mp3Encoder.open(Mp3EncoderConfig(48_000, 2, 192), output).use { encoder ->
        for (pcmBlock in pcmBlocks) encoder.writePcm16Le(pcmBlock)
        val statistics = encoder.finish()
    }
}
```

The caller owns the output stream and destination. Publish the destination only
after `finish()` and output close succeed. `close()` discards an unfinished export;
`cancel()` can be called from another thread. [API reference](docs/API.md).

## npm distribution

Install the public package from npm:

```sh
npm install uwdev-mp3codec@0.3.0
npx uwdev-mp3codec verify
npx uwdev-mp3codec maven-path
npx uwdev-mp3codec aar-path
npx uwdev-mp3codec export-aar-path
npx uwdev-mp3codec demo-path
npx uwdev-mp3codec example-path
```

The [npm registry](https://www.npmjs.com/package/uwdev-mp3codec) and the
[GitHub release](https://github.com/unicornwhodev/uwdev-mp3codec/releases/tag/v0.3.0)
provide the same tarball. Direct installation from the release is also supported:

```sh
npm install https://github.com/unicornwhodev/uwdev-mp3codec/releases/download/v0.3.0/uwdev-mp3codec-0.3.0.tgz
```

The npm package distributes both Android AARs, the Maven repository, the full demo
project, installable APK and English documentation, with small Node.js
helpers that locate and verify them. It has no runtime dependencies and no install
scripts. Encoding runs through the Android Kotlin/JNI API; this package does not
provide JavaScript, browser or WebAssembly audio encoding.

```js
const codec = require('uwdev-mp3codec');
console.log(codec.coordinate);
// coordinate/getAarPath retain their 0.2.0 core meaning for compatibility.
console.log(codec.exportCoordinate);
console.log(codec.getMavenRepositoryPath());
console.log(codec.getExampleProjectPath());
codec.verifyArtifacts();
```

## Qualification

The bundled core AAR is byte-identical to the artifact used for the completed audio
qualification: 60 encodes on a physical Android device, 528 extended MPEG/peak
checks, 264 signal cases and 204 edge cases. Android lifecycle and R8 consumer
tests, three native ABIs, API 26, real 16 KiB emulator pages, ASan and UBSan were
checked. Targeted human listening was accepted. [Qualification summary](docs/QUALIFICATION.md).

The native stream includes encoder delay and terminal padding; version 0.2.0 does
not write gapless metadata. Peak checks use the documented reconstruction method.
See [codec details](docs/CODEC.md) and [peak protection](docs/PEAK_PROTECTION.md).

The 0.3.0 facade passed 25 JVM tests, all 24 input/bitrate configurations on OPPO
ARM64/API 33 with 72 byte-identical direct/PCM/WAV comparisons, decoder-to-end
checks and Release/R8 integration tests. See [export validation](docs/EXPORT_VALIDATION.md)
for executed checks and the limits of this additional campaign.

## Build and test locally

Build tools: JDK 17, Android SDK 36, NDK 27.2.12479018 and CMake 3.22.1.

```sh
./gradlew :encoder-export:testDebugUnitTest :encoder-export:assembleRelease
python tools/validate_export.py --android-serial DEVICE_SERIAL
```

The facade resolves the frozen Maven core and does not rebuild it. Native source
development is separate from consuming the qualified binary:

```sh
cmake -S native-tests -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
npm test
npm audit
```

On Windows, use `gradlew.bat`. Kotlin consumers use Kotlin 2.2.21 and JVM target 17.
All validation and publication commands are local; this repository contains no
GitHub Actions workflows.

## License and attribution

Copyright 2026 **Unicorn Who Dev**. Original project code is licensed under the
[MIT License](LICENSE), including commercial use, modification and redistribution
with the copyright and permission notice retained. Keep [NOTICE.md](NOTICE.md)
and applicable [third-party notices](third-party-notices/). Attributed numerical
data, the Gradle Wrapper and the statically linked C++ runtime retain their own
license terms. They are not relicensed as original MIT code.
