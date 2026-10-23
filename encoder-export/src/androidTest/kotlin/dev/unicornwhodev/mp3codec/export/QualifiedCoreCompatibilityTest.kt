// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export

import android.media.MediaCodec
import android.media.MediaExtractor
import android.os.Looper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.unicornwhodev.mp3codec.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.*
import java.security.MessageDigest
import java.util.concurrent.*
import kotlin.math.PI
import kotlin.math.sin

@RunWith(AndroidJUnit4::class)
class QualifiedCoreCompatibilityTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    private fun pcm(rate: Int, channels: Int): ByteArray = ByteArray((rate / 8 + 7) * channels * 2).also { bytes ->
        for (i in 0 until bytes.size / 2) {
            val frame = i / channels
            val channel = i % channels
            val value = (sin(2 * PI * (if (channel == 0) 997 else 1733) * frame / rate) * 7000).toInt()
            bytes[i * 2] = value.toByte(); bytes[i * 2 + 1] = (value shr 8).toByte()
        }
    }
    private fun wav(pcm: ByteArray, rate: Int, channels: Int): ByteArray {
        fun le(value: Int, count: Int) = ByteArray(count) { (value shr (8 * it)).toByte() }
        val junk = "JUNK".toByteArray() + le(3, 4) + byteArrayOf(1, 2, 3, 0)
        val fmt = "fmt ".toByteArray() + le(16, 4) + le(1, 2) + le(channels, 2) + le(rate, 4) + le(rate * channels * 2, 4) + le(channels * 2, 2) + le(16, 2)
        val body = "WAVE".toByteArray() + junk + fmt + "data".toByteArray() + le(pcm.size, 4) + pcm
        return "RIFF".toByteArray() + le(body.size, 4) + body
    }

    @Test fun facadeAndWavMatchQualifiedCoreInAll24Configurations() {
        val evidence = File(context.getExternalFilesDir(null), "export-validation").apply { mkdirs() }
        val results = JSONArray()
        for (rate in listOf(44_100, 48_000, 96_000)) for (channels in 1..2) for (bitrate in listOf(128, 192, 256, 320)) {
            val input = pcm(rate, channels)
            val expected = ByteArrayOutputStream().also { output ->
                Mp3Encoder.open(Mp3EncoderConfig(rate, channels, bitrate), output).use { encoder ->
                    encoder.writePcm16Le(input)
                    encoder.finish()
                }
            }.toByteArray()
            val stem = "$rate-$channels-$bitrate"
            val raw = File(evidence, "$stem-pcm.mp3")
            val wavOutput = File(evidence, "$stem-wav.mp3")
            val fragmented = object : ByteArrayInputStream(input) {
                override fun read(bytes: ByteArray, offset: Int, length: Int) = super.read(bytes, offset, minOf(length, 13))
            }
            val options = Mp3ExportOptions(bitrateKbps = bitrate, overwrite = true, blockFrames = 257)
            val actual = Mp3Export.encode(PcmSources.pcm(fragmented, PcmFormat(rate, channels)), raw, options)
            Mp3Export.encode(PcmSources.wav(ByteArrayInputStream(wav(input, rate, channels))), wavOutput, options)
            assertArrayEquals("PCM $stem", expected, raw.readBytes())
            assertArrayEquals("WAV $stem", expected, wavOutput.readBytes())
            assertEquals(input.size.toLong() / (channels * 2), actual.statistics.inputFrames)
            assertEquals(if (rate == 96_000) 48_000 else rate, actual.statistics.outputSampleRate)
            val decoded = decodeToEnd(raw)
            assertTrue(decoded > 0)
            File(evidence, "$stem-direct.mp3").writeBytes(expected)
            results.put(JSONObject().put("configuration", stem).put("direct_sha256", sha(expected))
                .put("pcm_sha256", sha(raw.readBytes())).put("wav_sha256", sha(wavOutput.readBytes()))
                .put("input_frames", actual.statistics.inputFrames).put("android_decoded_bytes", decoded))
        }
        File(evidence, "compatibility.json").writeText(JSONObject().put("status", "PASS").put("core_version", "0.2.0").put("cases", results).toString(2))
    }

    private fun decodeToEnd(file: File): Long {
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(file.absolutePath)
            assertEquals(1, extractor.trackCount)
            val format = extractor.getTrackFormat(0)
            extractor.selectTrack(0)
            val codec = MediaCodec.createDecoderByType(checkNotNull(format.getString("mime")))
            try {
                codec.configure(format, null, null, 0); codec.start()
                var inputEos = false
                var bytes = 0L
                val info = MediaCodec.BufferInfo()
                val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
                while (System.nanoTime() < deadline) {
                    if (!inputEos) {
                        val index = codec.dequeueInputBuffer(10_000)
                        if (index >= 0) {
                            val count = extractor.readSampleData(checkNotNull(codec.getInputBuffer(index)), 0)
                            if (count < 0) {
                                codec.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputEos = true
                            } else {
                                codec.queueInputBuffer(index, 0, count, extractor.sampleTime, 0); extractor.advance()
                            }
                        }
                    }
                    val output = codec.dequeueOutputBuffer(info, 10_000)
                    if (output >= 0) {
                        bytes += info.size
                        codec.releaseOutputBuffer(output, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) return bytes
                    }
                }
                error("Android decode did not reach end of stream")
            } finally { codec.release() }
        } finally { extractor.release() }
    }

    @Test fun asyncCallbacksUseRequestedExecutorAndCancellationCleansOutput() {
        val worker = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor { Thread(it, "export-callback-test") }
        val directory = File(context.cacheDir, "export-cancel-test").apply { mkdirs() }
        val output = File(directory, "result.mp3")
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val terminal = CountDownLatch(1)
        var callbackThread: String? = null
        var callbackFailure: Throwable? = null
        val stream = object : ByteArrayInputStream(pcm(48_000, 2)) {
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
                entered.countDown(); assertTrue(release.await(10, TimeUnit.SECONDS))
                return super.read(bytes, offset, length)
            }
        }
        try {
            val job = Mp3Export.start(PcmSources.pcm(stream, PcmFormat(48_000, 2)), output, worker,
                Mp3ExportOptions(overwrite = true), callbacks, object : Mp3ExportObserver() {
                    override fun onFailure(failure: Throwable) { callbackThread = Thread.currentThread().name; callbackFailure = failure; terminal.countDown() }
                })
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            assertTrue(job.cancel()); release.countDown()
            assertThrows(Mp3CancelledException::class.java) { job.await(10, TimeUnit.SECONDS) }
            assertTrue(terminal.await(10, TimeUnit.SECONDS))
            assertEquals("export-callback-test", callbackThread)
            assertTrue(callbackFailure is Mp3CancelledException)
            assertFalse(output.exists())
            assertTrue(directory.listFiles()!!.none { it.name.endsWith(".part") })
        } finally { release.countDown(); worker.shutdownNow(); callbacks.shutdownNow() }
    }

    @Test fun mainThreadBlockingExportIsRejectedBeforeOpeningInput() {
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            assertTrue(Looper.myLooper() === Looper.getMainLooper())
            assertThrows(Mp3StateException::class.java) {
                Mp3Export.encode(PcmSource { error("must not open") }, File(context.cacheDir, "main-thread.mp3"))
            }
        }
    }
}
