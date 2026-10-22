# uwdev-mp3codec

**Stable Android PCM-to-MP3 encoding library, version 0.2.0.**

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

## Install with Gradle

Add the public, version-pinned Maven repository in `settings.gradle.kts`:

```kotlin
dependencyResolutionManagement {
    repositories {
        maven { url = uri("https://raw.githubusercontent.com/unicornwhodev/uwdev-mp3codec/v0.2.0/maven") }
        google()
        mavenCentral()
    }
}
```

Then add the dependency to your Android module:

```kotlin
dependencies {
    implementation("io.github.unicornwhodev:uwdev-mp3codec:0.2.0")
}
```

The release also provides a downloadable local Maven repository and a standalone
AAR. See the [integration guide](docs/INTEGRATION.md) for offline distribution,
direct AAR installation, required Kotlin runtime and a safe export example.

## Use the Android encoder

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

Install the public release tarball directly; this installation requires no registry credentials.

```sh
npm install https://github.com/unicornwhodev/uwdev-mp3codec/releases/download/v0.2.0/uwdev-mp3codec-0.2.0.tgz
npx uwdev-mp3codec verify
npx uwdev-mp3codec maven-path
npx uwdev-mp3codec aar-path
```

The npm package distributes the Android AAR and Maven repository, with small Node.js
helpers that locate and verify them. It has no runtime dependencies and no install
scripts. Encoding runs through the Android Kotlin/JNI API; this package does not
provide JavaScript, browser or WebAssembly audio encoding.

```js
const codec = require('uwdev-mp3codec');
console.log(codec.coordinate);
console.log(codec.getMavenRepositoryPath());
codec.verifyArtifacts();
```

## Qualification

The released AAR is byte-identical to the artifact used for the completed audio
qualification: 60 encodes on a physical Android device, 528 extended MPEG/peak
checks, 264 signal cases and 204 edge cases. Android lifecycle and R8 consumer
tests, three native ABIs, API 26, real 16 KiB emulator pages, ASan and UBSan were
checked. Targeted human listening was accepted. [Qualification summary](docs/QUALIFICATION.md).

The native stream includes encoder delay and terminal padding; version 0.2.0 does
not write gapless metadata. Peak checks use the documented reconstruction method.
See [codec details](docs/CODEC.md) and [peak protection](docs/PEAK_PROTECTION.md).

## Build and test locally

Build tools: JDK 17, Android SDK 36, NDK 27.2.12479018 and CMake 3.22.1.

```sh
./gradlew :encoder-android:assembleRelease :encoder-android:testReleaseUnitTest
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
