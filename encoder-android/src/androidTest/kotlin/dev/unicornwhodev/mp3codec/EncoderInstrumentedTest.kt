// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Debug
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.lang.ref.ReferenceQueue
import java.lang.ref.WeakReference
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.PI
import kotlin.math.sin
import org.junit.Assert.*
import org.junit.Test

class EncoderInstrumentedTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun pcm(rate: Int, channels: Int, frames: Int): ByteArray = ByteArray(frames * channels * 2).also { bytes ->
        repeat(frames) { frame ->
            repeat(channels) { channel ->
                val sample = (sin(2.0 * PI * (if (channel == 0) 1_000.0 else 700.0) * frame / rate) * 12_000).toInt()
                val index = (frame * channels + channel) * 2
                bytes[index] = sample.toByte()
                bytes[index + 1] = (sample shr 8).toByte()
            }
        }
    }

    @Test fun all24ConfigurationsDecodeOnAndroid() {
        for (rate in listOf(44_100, 48_000, 96_000)) for (channels in 1..2) for (bitrate in listOf(128, 192, 256, 320)) {
            val source = pcm(rate, channels, rate / 4)
            val file = File.createTempFile("uwdev-$rate-$channels-$bitrate-", ".mp3", context.cacheDir)
            try {
                val stats = file.outputStream().use { output ->
                    Mp3Encoder.open(Mp3EncoderConfig(rate, channels, bitrate), output).use { encoder ->
                        var offset = 0
                        val blocks = intArrayOf(1, 4096, 19, 71)
                        var block = 0
                        while (offset < source.size) {
                            val size = minOf(blocks[block++ % blocks.size] * 2 * channels, source.size - offset)
                            encoder.writePcm16Le(source, offset, size)
                            offset += size
                        }
                        encoder.finish().also { assertEquals(it, encoder.finish()) }
                    }
                }
                assertEquals((rate / 4).toLong(), stats.inputFrames)
                assertEquals(file.length(), stats.outputBytes)
                assertTrue(stats.outputBytes > 0)
                assertEquals(if (rate == 96_000) 48_000 else rate, stats.outputSampleRate)
                val protection = requireNotNull(stats.peakProtection)
                assertTrue(protection.reconstructedTruePeak <= 0.995001)
                assertTrue(protection.minimumLinearGain > 0.0)
                assertTrue(protection.minimumLinearGain <= 1.0)
                assertTrue(decode(file, stats.outputSampleRate, channels) > 0)
            } finally { file.delete() }
        }
    }

    /** Android decoding is an external validation path, never production encoding. */
    private fun decode(file: File, rate: Int, channels: Int): Long {
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            extractor.setDataSource(file.absolutePath)
            assertTrue(extractor.trackCount > 0)
            extractor.selectTrack(0)
            val format = extractor.getTrackFormat(0)
            assertEquals(rate, format.getInteger(MediaFormat.KEY_SAMPLE_RATE))
            assertEquals(channels, format.getInteger(MediaFormat.KEY_CHANNEL_COUNT))
            codec = MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME)!!)
            codec.configure(format, null, null, 0)
            codec.start()
            var inputEos = false
            var outputEos = false
            var decodedBytes = 0L
            val info = MediaCodec.BufferInfo()
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20)
            while (!outputEos && System.nanoTime() < deadline) {
                if (!inputEos) {
                    val index = codec.dequeueInputBuffer(10_000)
                    if (index >= 0) {
                        val buffer = codec.getInputBuffer(index)!!
                        buffer.clear()
                        val size = extractor.readSampleData(buffer, 0)
                        if (size < 0) {
                            codec.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputEos = true
                        } else {
                            codec.queueInputBuffer(index, 0, size, extractor.sampleTime, 0)
                            extractor.advance()
                        }
                    }
                }
                val index = codec.dequeueOutputBuffer(info, 10_000)
                if (index >= 0) {
                    decodedBytes += info.size
                    outputEos = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                    codec.releaseOutputBuffer(index, false)
                }
            }
            assertTrue("Android decoder must reach EOS", outputEos)
            return decodedBytes
        } finally {
            codec?.release()
            extractor.release()
        }
    }

    @Test fun validatesLifecycleAndOutputOwnership() {
        var closed = false
        var flushed = false
        val output = object : ByteArrayOutputStream() {
            override fun close() { closed = true; super.close() }
            override fun flush() { flushed = true; super.flush() }
        }
        val encoder = Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), output)
        encoder.writePcm16Le(byteArrayOf())
        encoder.writePcm16Le(pcm(44_100, 1, 1))
        val stats = encoder.finish()
        assertEquals(stats, encoder.finish())
        assertThrows(Mp3StateException::class.java) { encoder.writePcm16Le(byteArrayOf()) }
        encoder.close()
        encoder.close()
        assertEquals(stats, encoder.finish())
        assertFalse(closed)
        assertFalse(flushed)
    }

    @Test fun emptyInputAndPrematureCloseDoNotProduceFakeFiles() {
        val output = ByteArrayOutputStream()
        Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), output).use {
            assertThrows(Mp3EncoderException::class.java) { it.finish() }
        }
        assertEquals(0, output.size())
        val cancelled = Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), output)
        cancelled.cancel()
        assertThrows(Mp3CancelledException::class.java) { cancelled.writePcm16Le(byteArrayOf()) }
        cancelled.close()
        val closed = Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), output)
        closed.close()
        assertThrows(Mp3StateException::class.java) { closed.finish() }
    }

    @Test fun outputErrorsPreserveTheirCause() {
        val expected = IOException("injected write failure")
        val output = object : OutputStream() {
            override fun write(value: Int) { throw expected }
            override fun write(data: ByteArray, offset: Int, length: Int) { throw expected }
        }
        Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), output).use { encoder ->
            val failure = assertThrows(Mp3OutputException::class.java) {
                encoder.writePcm16Le(pcm(44_100, 1, 8192))
                encoder.finish()
            }
            assertSame(expected, failure.cause)
            assertThrows(Mp3StateException::class.java) { encoder.finish() }
        }
    }

    @Test fun cancellationCanBeSignalledWhileOutputIsBlocked() {
        val entered = CountDownLatch(1)
        val resume = CountDownLatch(1)
        val output = object : OutputStream() {
            override fun write(value: Int) = Unit
            override fun write(data: ByteArray, offset: Int, length: Int) {
                entered.countDown()
                check(resume.await(10, TimeUnit.SECONDS))
            }
        }
        val encoder = Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), output)
        val executor = Executors.newSingleThreadExecutor()
        try {
            val future = executor.submit<Throwable?> {
                try {
                    encoder.writePcm16Le(pcm(44_100, 1, 44_100))
                    encoder.finish()
                    null
                } catch (failure: Throwable) { failure }
            }
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            val start = System.nanoTime()
            encoder.cancel()
            assertTrue("cancel must not wait for caller output", System.nanoTime() - start < TimeUnit.SECONDS.toNanos(1))
            resume.countDown()
            assertTrue(future.get(10, TimeUnit.SECONDS) is Mp3CancelledException)
        } finally {
            resume.countDown()
            encoder.close()
            executor.shutdownNow()
        }
    }

    @Test fun closeWhileOutputIsBlockedKeepsActiveNativeCallAlive() {
        val entered = CountDownLatch(1)
        val resume = CountDownLatch(1)
        val output = object : OutputStream() {
            override fun write(value: Int) = Unit
            override fun write(data: ByteArray, offset: Int, length: Int) {
                entered.countDown()
                check(resume.await(10, TimeUnit.SECONDS))
            }
        }
        val encoder = Mp3Encoder.open(Mp3EncoderConfig(48_000, 2), output)
        val executor = Executors.newSingleThreadExecutor()
        try {
            val writer = executor.submit<Throwable?> {
                try { encoder.writePcm16Le(pcm(48_000, 2, 16_384)); null }
                catch (failure: Throwable) { failure }
            }
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            val start = System.nanoTime()
            encoder.close()
            assertTrue("close must not wait for caller output", System.nanoTime() - start < TimeUnit.SECONDS.toNanos(1))
            assertThrows(Mp3StateException::class.java) { encoder.finish() }
            resume.countDown()
            assertTrue(writer.get(10, TimeUnit.SECONDS) is Mp3CancelledException)
            encoder.close()
        } finally { resume.countDown(); encoder.close(); executor.shutdownNow() }
    }

    @Test fun multipleSessionsAndChunkSizesAreIndependent() {
        val source = pcm(48_000, 2, 8_000)
        val outputs = List(3) { ByteArrayOutputStream() }
        val encoders = outputs.map { Mp3Encoder.open(Mp3EncoderConfig(48_000, 2), it) }
        try {
            encoders[0].writePcm16Le(source)
            for (offset in source.indices step 4) {
                encoders[1].writePcm16Le(source, offset, 4)
                encoders[2].writePcm16Le(source, offset, 4)
            }
            encoders.forEach { it.finish() }
            assertArrayEquals(outputs[0].toByteArray(), outputs[1].toByteArray())
            assertArrayEquals(outputs[1].toByteArray(), outputs[2].toByteArray())
        } finally { encoders.forEach { it.close() } }
    }

    /** A retained JNI global reference would keep the caller-owned stream alive. */
    @Test fun repeatedTerminalPathsReleaseNativeMemoryAndStreamReferences() {
        val source = pcm(44_100, 1, 4_096)
        repeat(3) { repeatedSession(it, source, ReferenceQueue()) }
        System.gc()
        System.runFinalization()
        val nativeBefore = Debug.getNativeHeapAllocatedSize()
        val queue = ReferenceQueue<OutputStream>()
        val waiting = List(36) { repeatedSession(it % 3, source, queue) }.toMutableSet()
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
        // Never dereference the streams: a get() immediately before GC can keep a
        // temporary strong reference live in the ART interpreter's stack/registers.
        while (waiting.isNotEmpty() && System.nanoTime() < deadline) {
            System.gc()
            System.runFinalization()
            var collected = queue.poll()
            while (collected != null) {
                assertTrue("Only this run's references are queued", waiting.remove(collected))
                collected = queue.poll()
            }
            Thread.sleep(20)
        }
        val retainedStreams = waiting.size
        val nativeAfter = Debug.getNativeHeapAllocatedSize()
        Log.i("UwdevMp3ResourceTest", "sessions=36 native_before=$nativeBefore native_after=$nativeAfter retained_streams=$retainedStreams")
        assertEquals("Finished, cancelled and failed sessions must release JNI stream references", 0, retainedStreams)
        assertTrue("Repeated sessions must not retain unbounded native allocations: before=$nativeBefore after=$nativeAfter",
            nativeAfter - nativeBefore < 4L * 1024 * 1024)
    }

    private fun repeatedSession(terminalPath: Int, source: ByteArray, queue: ReferenceQueue<OutputStream>): WeakReference<OutputStream> {
        val output = object : OutputStream() {
            override fun write(value: Int) {
                if (terminalPath == 2) throw IOException("repeated failure")
            }
            override fun write(data: ByteArray, offset: Int, length: Int) {
                assertTrue("JNI output writes must be bounded", length <= 32 * 1024)
                if (terminalPath == 2) throw IOException("repeated failure")
            }
        }
        val reference = WeakReference<OutputStream>(output, queue)
        Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), output).use { encoder ->
            when (terminalPath) {
                0 -> { encoder.writePcm16Le(source); encoder.finish() }
                1 -> { encoder.writePcm16Le(source, 0, 2); encoder.cancel() }
                else -> assertThrows(Mp3OutputException::class.java) {
                    encoder.writePcm16Le(source)
                    encoder.finish()
                }
            }
        }
        return reference
    }

    @Test fun encodingOnMainThreadIsRejected() {
        Mp3Encoder.open(Mp3EncoderConfig(44_100, 1), ByteArrayOutputStream()).use { encoder ->
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertThrows(Mp3StateException::class.java) { encoder.writePcm16Le(byteArrayOf()) }
                assertThrows(Mp3StateException::class.java) { encoder.finish() }
            }
        }
    }
}
