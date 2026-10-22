// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.sample

import android.app.Activity
import android.media.MediaPlayer
import android.os.Bundle
import android.os.Build
import android.os.Debug
import android.os.SystemClock
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import dev.unicornwhodev.mp3codec.Mp3Encoder
import dev.unicornwhodev.mp3codec.Mp3EncoderConfig
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.PI
import kotlin.math.sin
import org.json.JSONObject

/** Standalone native Android demonstration; no network or storage permissions. */
class MainActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val activeEncoder = AtomicReference<Mp3Encoder?>()
    private val destroying = AtomicBoolean(false)
    private var player: MediaPlayer? = null
    private lateinit var status: TextView
    private lateinit var encodeButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 56, 32, 32)
        }
        status = TextView(this).apply { text = "Generate a 5-second stereo signal, encode locally, then play the MP3." }
        encodeButton = Button(this).apply {
            text = "Encode and play"
            setOnClickListener { runExport() }
        }
        val cancelButton = Button(this).apply {
            text = "Cancel export"
            setOnClickListener { activeEncoder.get()?.cancel() }
        }
        layout.addView(status)
        layout.addView(encodeButton)
        layout.addView(cancelButton)
        setContentView(layout)
    }

    private fun runExport() {
        encodeButton.isEnabled = false
        status.text = "Encoding on a worker thread…"
        worker.execute {
            if (destroying.get()) return@execute
            val temporary = File.createTempFile("audio-", ".part", cacheDir)
            try {
                val destination = File(filesDir, "demo.mp3")
                val started = SystemClock.elapsedRealtimeNanos()
                val cpuStarted = Debug.threadCpuTimeNanos()
                val nativeBefore = Debug.getNativeHeapAllocatedSize()
                var nativeObservedPeak = nativeBefore
                val stats = temporary.outputStream().use { output ->
                    Mp3Encoder.open(Mp3EncoderConfig(44_100, 2, 192), output).use { encoder ->
                        activeEncoder.set(encoder)
                        if (destroying.get()) encoder.cancel()
                        nativeObservedPeak = maxOf(nativeObservedPeak, Debug.getNativeHeapAllocatedSize())
                        val frames = 44_100 * 5
                        val block = ByteArray(4096 * 4)
                        var first = 0
                        while (first < frames) {
                            val count = minOf(4096, frames - first)
                            repeat(count) { index ->
                                repeat(2) { channel ->
                                    val t = (first + index).toDouble() / 44_100
                                    val frequency = if (channel == 0) 440.0 else 660.0
                                    val envelope = minOf(1.0, t * 20.0, (5.0 - t) * 20.0).coerceAtLeast(0.0)
                                    val value = (sin(2.0 * PI * frequency * t) * 12_000.0 * envelope).toInt()
                                    val offset = (index * 2 + channel) * 2
                                    block[offset] = value.toByte()
                                    block[offset + 1] = (value shr 8).toByte()
                                }
                            }
                            encoder.writePcm16Le(block, 0, count * 4)
                            nativeObservedPeak = maxOf(nativeObservedPeak, Debug.getNativeHeapAllocatedSize())
                            first += count
                        }
                        encoder.finish()
                    }
                }
                val seconds = (SystemClock.elapsedRealtimeNanos() - started) / 1_000_000_000.0
                val cpuSeconds = (Debug.threadCpuTimeNanos() - cpuStarted) / 1_000_000_000.0
                val nativeAfterClose = Debug.getNativeHeapAllocatedSize()
                Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING)
                val report = JSONObject().apply {
                    put("device_model", Build.MODEL)
                    put("android_version", Build.VERSION.RELEASE)
                    put("android_api", Build.VERSION.SDK_INT)
                    put("page_size", android.system.Os.sysconf(android.system.OsConstants._SC_PAGESIZE))
                    put("supported_abis", Build.SUPPORTED_ABIS.joinToString(","))
                    put("sample_rate", stats.outputSampleRate)
                    put("channels", stats.channels)
                    put("bitrate_kbps", stats.bitrateKbps)
                    put("source_seconds", 5.0)
                    put("input_frames", stats.inputFrames)
                    put("output_bytes", stats.outputBytes)
                    put("mpeg_frames", stats.encodedMpegFrames)
                    put("export_elapsed_seconds", seconds)
                    put("worker_cpu_seconds", cpuSeconds)
                    put("source_seconds_per_elapsed_second", 5.0 / seconds)
                    put("native_heap_before_bytes", nativeBefore)
                    put("native_heap_sampled_peak_bytes", nativeObservedPeak)
                    put("native_heap_after_close_bytes", nativeAfterClose)
                    put("native_heap_note", "Process native allocations sampled after open and each PCM block; not a continuous RSS peak or an instance-isolated measurement")
                    put("timing_note", "Includes signal generation, encoder creation, native encoding and local file writing/closing")
                    put("playback_started", false)
                    put("playback_completed", false)
                }
                File(filesDir, "benchmark.json").writeText(report.toString(2))
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    status.text = String.format(Locale.US,
                        "%,d PCM frames → %,d MPEG frames\n%,d bytes · %d Hz · %d kbit/s\nEncoding %.3f s · %.2f× real time\n%s",
                        stats.inputFrames, stats.encodedMpegFrames, stats.outputBytes,
                        stats.outputSampleRate, stats.bitrateKbps, seconds, 5.0 / seconds, destination.name)
                    encodeButton.isEnabled = true
                    play(destination, report)
                }
            } catch (failure: Exception) {
                temporary.delete()
                runOnUiThread {
                    if (!isDestroyed) {
                        status.text = "Export failed: ${failure.message}"
                        encodeButton.isEnabled = true
                    }
                }
            } finally { activeEncoder.set(null) }
        }
    }

    private fun play(file: File, report: JSONObject) {
        player?.release()
        player = MediaPlayer().apply {
            setDataSource(file.absolutePath)
            setOnPreparedListener {
                it.start()
                report.put("playback_started", true)
                savePlaybackReport(report)
            }
            setOnCompletionListener {
                report.put("playback_completed", true)
                status.append("\nAndroid playback completed.")
                savePlaybackReport(report)
            }
            setOnErrorListener { _, what, extra ->
                status.append("\nPlayback failed ($what/$extra)")
                report.put("playback_error", "$what/$extra")
                savePlaybackReport(report)
                true
            }
            prepareAsync()
        }
    }

    private fun savePlaybackReport(report: JSONObject) {
        val serialized = report.toString(2)
        if (!worker.isShutdown) worker.execute {
            File(filesDir, "benchmark.json").writeText(serialized)
            // Explicit local QA export of the generated demo tone and its result.
            if (intent.getBooleanExtra("qualification_evidence", false)) {
                val evidence = File(getExternalFilesDir(null), "qualification-r8").apply { mkdirs() }
                File(filesDir, "demo.mp3").copyTo(File(evidence, "demo.mp3"), overwrite = true)
                File(evidence, "result.json").writeText(serialized)
            }
        }
    }

    override fun onDestroy() {
        destroying.set(true)
        activeEncoder.get()?.cancel()
        worker.shutdownNow()
        player?.release()
        player = null
        super.onDestroy()
    }
}
