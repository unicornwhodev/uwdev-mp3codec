# Android integration

## Maven repository

Use `io.github.unicornwhodev:uwdev-mp3codec:0.2.0` from the public repository shown
in the root README, or download the Maven ZIP from the GitHub release and extract
it into `local-maven` in your application project. Keep Google and Maven Central
available for your other build dependencies.

```kotlin
dependencyResolutionManagement {
    repositories {
        maven { url = uri(rootDir.resolve("local-maven")) }
        google()
        mavenCentral()
    }
}
```

```kotlin
dependencies {
    implementation("io.github.unicornwhodev:uwdev-mp3codec:0.2.0")
}
```

## npm-assisted Android builds

Install the npm tarball from the public GitHub release shown in the root README,
then run `npx uwdev-mp3codec maven-path` to locate
its bundled repository. With `node_modules` in your application project root:

```kotlin
maven { url = uri(rootDir.resolve("node_modules/uwdev-mp3codec/maven")) }
```

The npm helper verifies artifact hashes and returns paths; it does not encode
audio in JavaScript or register a React Native bridge automatically.

## Direct AAR

Copy `uwdev-mp3codec-0.2.0.aar` from the release into `app/libs`:

```kotlin
dependencies {
    implementation(files("libs/uwdev-mp3codec-0.2.0.aar"))
    implementation("org.jetbrains.kotlin:kotlin-stdlib:2.2.21")
}
```

The Maven metadata declares the Kotlin dependency automatically. Use Android API
26 or later, Kotlin 2.2.21 and JVM target 17. Supported ABIs are arm64-v8a,
armeabi-v7a and x86_64. Native libraries and consumer R8 rules are included.
Applications importing the AAR do not compile the codec's C++ sources.

## Commit an export only after success

Call this example from a worker thread. The destination parent must already exist.
Each stereo PCM block contains a multiple of four bytes. Pass PCM samples without
a WAV header. Application code owns storage permissions and document-provider URIs.

```kotlin
import dev.unicornwhodev.mp3codec.Mp3Encoder
import dev.unicornwhodev.mp3codec.Mp3EncoderConfig
import dev.unicornwhodev.mp3codec.Mp3EncodingStats
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

fun exportMp3(destination: File, blocks: Sequence<ByteArray>): Mp3EncodingStats {
    val parent = requireNotNull(destination.absoluteFile.parentFile)
    val temporary = File.createTempFile("uwdev-", ".part", parent)
    try {
        val statistics = temporary.outputStream().buffered().use { output ->
            Mp3Encoder.open(Mp3EncoderConfig(48_000, 2, 192), output).use { encoder ->
                for (block in blocks) encoder.writePcm16Le(block)
                encoder.finish()
            }
        }
        Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING)
        return statistics
    } catch (failure: Exception) {
        temporary.delete()
        throw failure
    }
}
```

`finish()` drains and finalizes the stream. `close()` releases resources and
discards unfinished input; it does not close the caller's stream. Use `cancel()`
for cancellation from another thread. See [API.md](API.md) for typed errors,
concurrency, exact frame counters and peak-protection diagnostics.

The output contains encoder delay and padding. This version has no gapless tag.
The [codec specification](CODEC.md) describes timing and the 96-to-48 kHz FIR.

## Commercial use and credits

Commercial use is permitted by the MIT project license. Retain the copyright and
permission notice, `NOTICE.md` and the applicable files in `third-party-notices`.
The AAR includes notices under `META-INF/uwdev-mp3codec`. Downstream packaging
must preserve the relevant attributions when redistributing the library.
