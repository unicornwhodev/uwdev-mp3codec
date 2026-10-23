# PCM/WAV export facade

The optional `encoder-export` module provides blocking and asynchronous file exports
around **the frozen, qualified `uwdev-mp3codec:0.2.0` AAR**. It does not modify or
rebuild the native encoder. Its stable coordinate is
`io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0`.
The 0.3.0 release and npm package contain both modules, the SDK and the demo.

The facade adds no runtime dependency beyond the qualified core and its Kotlin
runtime. It does not require coroutines, Compose, AppCompat, Media3, network access
or storage permissions. Applications choose their worker and callback executors.

## Install the stable release

Add the version-pinned repository to `settings.gradle.kts`:

```kotlin
maven { url = uri("https://raw.githubusercontent.com/unicornwhodev/uwdev-mp3codec/v0.3.0/maven") }
```

Then use `implementation("io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0")`.
Alternatively, extract the SDK from the [0.3.0 release](https://github.com/unicornwhodev/uwdev-mp3codec/releases/tag/v0.3.0),
or install `npm install uwdev-mp3codec@0.3.0` and use its `maven` directory.
The npm package also includes `example/android`, `demo/uwdev-mp3codec-demo.apk`,
the original demo WAV and all English documentation.

## Build from the source checkout

With JDK 17 and Android SDK 36 configured, run from the checkout:

```sh
./gradlew :encoder-export:publishReleasePublicationToStagingRepository
```

Use `gradlew.bat` on Windows. Add both local repositories to your consumer's
`settings.gradle.kts`; `codecCheckout` below is the path to this checkout:

```kotlin
dependencyResolutionManagement {
    repositories {
        maven { url = uri("$codecCheckout/encoder-export/build/staging-repository") }
        maven { url = uri("$codecCheckout/maven") }
        google()
        mavenCentral()
    }
}
```

```kotlin
implementation("io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0")
```

The POM brings in `uwdev-mp3codec:0.2.0`. The export AAR intentionally contains no
second native library. For manual AAR installation include **both** the export AAR
and the qualified core AAR, plus `org.jetbrains.kotlin:kotlin-stdlib:2.2.21`.
Android API 26+, JVM target 17, native ABI support and the existing R8 rules remain
those of the qualified core. A binary consumer does not need an NDK or CMake.

After complete validation, `python tools/package_export.py` also creates a combined
Maven ZIP in `build/release-0.3.0`. Extract it and use that single directory as
a local Maven repository; it includes both modules and their metadata.

To package an immediately usable SDK with an installable demo:

```sh
python tools/package_export.py
./gradlew -p build/release-0.3.0/sdk/example/android :app:assembleRelease
python tools/validate_demo.py --android-serial DEVICE_SERIAL
python tools/package_export.py --with-demo
```

The resulting `uwdev-mp3codec-0.3.0-sdk.zip` includes English
documentation, Kotlin/Java encoding examples, a standalone Gradle demo project,
a signed non-debuggable R8 demo APK, the original sample WAV/provenance, both AARs,
the combined Maven repository, qualification summaries, licenses and checksums.
It contains no Gradle caches, build intermediates, signing key, credentials or
device logs. The demo project builds from the packaged binaries rather than the
codec source projects. It can be opened independently in Android Studio.

## Blocking export

Call from a worker thread. The destination parent must already exist.

```kotlin
import dev.unicornwhodev.mp3codec.export.*

val result = Mp3Export.fromWav(
    input = sourceWav,
    output = destinationMp3,
    preset = Mp3Preset.HIGH_256,
)
println(result.statistics.outputBytes)
```

`Mp3Preset` names map directly to the existing CBR bitrates:
`COMPACT_128`, `BALANCED_192`, `HIGH_256`, `MAXIMUM_320`.
They do not change the model, channel mode, gain or other encoder settings.

## Asynchronous export, progress and cancellation

```kotlin
val worker = java.util.concurrent.Executors.newSingleThreadExecutor()
val main = java.util.concurrent.Executor { command -> activity.runOnUiThread(command) }

val job = Mp3Export.start(
    source = PcmSources.wav(sourceWav),
    output = destinationMp3,
    worker = worker,
    options = Mp3ExportOptions(bitrateKbps = 256),
    callbackExecutor = main,
    observer = object : Mp3ExportObserver() {
        override fun onProgress(progress: Mp3ExportProgress) {
            // inputFraction is null for sources with unknown length.
            // 1.0 means all input was consumed; finalization/commit may still be running.
            renderProgress(progress.inputFraction, progress.phase)
        }
        override fun onSuccess(result: Mp3ExportResult) {
            showCompletedFile(result.output)
        }
        override fun onFailure(failure: Throwable) {
            showExportFailure(failure)
        }
    },
)

// From a cancel button or application lifecycle callback:
job.cancel()
// Let accepted work finish cleanup, then release the caller-owned executor:
worker.shutdown()
```

Supply an executor that actually runs work off the main thread. A direct executor
on the main thread is rejected. Callbacks use the supplied executor; omitting it
delivers callbacks on the worker. No global threads or Activity references are
created by the library. The application decides whether its export should survive
an Activity recreation. The sample cancels on destruction.

Progress phases are `ENCODING`, `FINALIZING`, `COMMITTING`. Default notification
interval is 100 ms. Progress is coalesced: at most one pending progress value and
one terminal notification are retained when a callback executor is slow.
Notifications run in order and stop after the terminal notification. Short exports
or slow callback executors can skip intermediate progress values/phases.

Observer failures do not invalidate a committed file. The asynchronous job records
an observer/executor failure in `callbackFailure`. `job.await()` (worker threads
only) returns or throws after cleanup; it does not wait for callback delivery.
`job.await(timeout, unit)` does not cancel on timeout. Never block the UI or wait
inside an export's own callbacks. The blocking `encode` observer runs on its caller;
its observer failures are isolated without a separate callback-error channel.

`cancel()` is cooperative and returns false once file commit has started or the
export has completed. A completed file is never rolled back by a late cancellation.
Built-in stream adapters check cancellation between reads, including WAV header and
metadata processing. A blocking caller/provider stream cannot be forcibly
interrupted; cleanup completes when that operation returns. A cancellation token
belongs to a single export.

Java callers can use the same API without a Kotlin Gradle plugin:

```java
PcmSource source = PcmSources.wav(() -> new java.io.FileInputStream(inputWav));
Mp3ExportJob job = Mp3Export.start(
    source, outputMp3, workerExecutor, new Mp3ExportOptions(256), mainExecutor,
    new Mp3ExportObserver() {
        @Override public void onSuccess(Mp3ExportResult result) {
            showCompletedFile(result.getOutput());
        }
        @Override public void onFailure(Throwable failure) {
            showExportFailure(failure);
        }
    });
```

## PCM sources and ownership

```kotlin
val format = PcmFormat(sampleRate = 48_000, channels = 2)
val fromFile = PcmSources.pcm(pcmFile, format)

// Recommended for repeated exports, document URIs and deferred opening:
val fromUri = PcmSources.wav(InputStreamFactory {
    contentResolver.openInputStream(wavUri) ?: error("Cannot open input document")
})
val rawFactory = PcmSources.pcm(format, InputStreamFactory { openRenderedPcm() })

// Existing streams are one-shot and borrowed by default:
val borrowed = PcmSources.pcm(inputStream, format, totalFrames = knownFrames)
val owned = PcmSources.pcm(inputStream, format, closeInput = true)
```

PCM is signed, interleaved 16-bit little-endian. Supported rates are 44,100, 48,000
and 96,000 Hz, with one or two channels. The core still performs its qualified
96-to-48 kHz conversion. No extra normalization, gain fitting, dither or channel
conversion is added. Partial byte reads are assembled into bounded whole-frame
blocks before JNI. Default block size is 4,096 PCM frames, configurable from 1 to
65,536. A partial frame at EOF, an incorrect declared frame count or empty input is
an input error. Sixteen consecutive zero-length reads fail rather than busy-loop.

File and factory adapters own their opened streams, including on parsing failure.
Borrowed streams remain open. `closeInput=true` transfers closing responsibility
once the reader is opened; if an export is cancelled before opening it, the caller
still owns a pre-opened stream. Prefer factories to avoid that ambiguity. Reusing
an existing-stream source fails explicitly; file and factory sources can be opened
again. Custom audio renderers may implement `PcmSource`/`PcmReader` and provide an
exact `totalFrames`, or null when unknown. Readers must honor the documented read
contract and keep format/length stable. Their close method owns their resources.

## Supported WAV subset

The parser accepts little-endian RIFF/WAVE with a single `fmt ` chunk describing
uncompressed PCM (`formatTag=1`), 16 bits per sample, and a single `data` chunk.
It verifies block alignment, byte rate, chunk sizes and the RIFF boundary. It skips
unknown chunks and odd-byte padding before/after data without encoding metadata.
The trailing RIFF chunks are also validated before committing the file.

Float WAV, compressed WAV, WAVE_FORMAT_EXTENSIBLE, RF64, RIFX, multiple data chunks
and unsupported rates/channels are rejected. Their conversion is not implicit.
The parser uses bounded buffers and does not assume every WAV has a 44-byte header.
The library does not render or mix a DAW project: supply the renderer's PCM stream.

## Destination safety and errors

The facade writes a temporary `.part` file **in the destination directory**.
It commits only after encoder `finish()`, output flush/close and source close have
succeeded. By default an existing destination is an error. For explicit
`overwrite=true`, replacement requires the filesystem's atomic-move support;
unsupported atomic replacement fails while preserving the old destination.
The facade never deletes the existing destination as a fallback.

Input and output cannot be the same known source file. For a custom stream/source,
the caller must avoid referring to the destination indirectly. Concurrent writers
to the same destination should be avoided. Temporary cleanup failures are surfaced
as suppressed output exceptions, rather than claimed as successful cleanup.

Errors use the existing typed codec exceptions: configuration, input, output,
state, cancellation, native and encoding failures retain their causes. Failed or
cancelled exports have no success notification. Statistics and peak-protection
diagnostics come from the original core, with its documented measurement scope.

## Complete Android sample

`sample-app` starts `ExportActivity`. It provides:

1. A system document picker for WAV input.
   An original bundled WAV can also be loaded without choosing an external file.
2. All four supported CBR bitrates.
3. Background export with progress and cancellation.
4. Android playback of the completed MP3.
5. A system document picker to save a copy of the completed MP3.

The original generated-tone `MainActivity` remains available as a non-exported
demonstration activity. The new sample adds no broad storage or network permission.
Only the complete local MP3 is copied to the selected destination. A document
provider does not guarantee atomic replacement: on a copy failure, the sample
attempts to remove the newly created document and reports if cleanup is unconfirmed.
It does not overwrite or delete a user-selected source document.

## Local validation

```sh
./gradlew :encoder-export:testDebugUnitTest :encoder-export:assembleRelease
./gradlew :sample-app:assembleRelease :sample-app:assembleReleaseAndroidTest -PuwdevLocalDeviceQa=true
python tools/validate_export.py --android-serial DEVICE_SERIAL
```

The local QA property signs the Release sample using the workstation's debug key;
it does not make the app debuggable or disable R8. It preserves the Kotlin runtime
needed by AndroidJUnitRunner in the instrumented sample; the application, facade
and codec are still processed by R8. Those QA rules are not shipped in either AAR.
No key is distributed. Android
checks compare direct core, fragmented PCM and WAV output in all 24 configurations,
decode to EOS, test cancellation and exercise the Release/R8 sample. A report in
`build/export-validation` separates executed checks from unavailable ones. See
[EXPORT_VALIDATION.md](EXPORT_VALIDATION.md). No CI or GitHub workflow is used.
