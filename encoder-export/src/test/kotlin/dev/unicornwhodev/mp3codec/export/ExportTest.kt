// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export

import dev.unicornwhodev.mp3codec.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.*
import java.util.concurrent.Executor

internal fun wavBytes(pcm: ByteArray, format: PcmFormat = PcmFormat(48_000, 2), oddChunk: Boolean = false, trailing: Boolean = false): ByteArray {
    fun le(value: Long, count: Int) = ByteArray(count) { (value shr (8 * it)).toByte() }
    fun chunk(id: String, bytes: ByteArray): ByteArray = id.toByteArray() + le(bytes.size.toLong(), 4) + bytes + if (bytes.size % 2 == 1) byteArrayOf(0) else byteArrayOf()
    val fmt = le(1, 2) + le(format.channels.toLong(), 2) + le(format.sampleRate.toLong(), 4) +
        le(format.sampleRate.toLong() * format.bytesPerFrame, 4) + le(format.bytesPerFrame.toLong(), 2) + le(16, 2)
    val body = "WAVE".toByteArray() + (if (oddChunk) chunk("JUNK", byteArrayOf(1, 2, 3)) else byteArrayOf()) +
        chunk("fmt ", fmt) + chunk("data", pcm) + (if (trailing) chunk("LIST", byteArrayOf(7, 8, 9)) else byteArrayOf())
    return "RIFF".toByteArray() + le(body.size.toLong(), 4) + body
}

class ExportTest {
    @get:Rule val directory = TemporaryFolder()
    private val format = PcmFormat(48_000, 2)
    private val pcm = ByteArray(4096 * 4 + 12) { (it * 31).toByte() }
    private val direct = Executor { it.run() }

    private class FakeEncoder(val output: OutputStream) : EncodingSession {
        val input = ByteArrayOutputStream()
        var closed = false
        var cancelled = false
        var afterWrite: (() -> Unit)? = null
        var beforeFinish: (() -> Unit)? = null
        var failingFinish = false
        override fun write(bytes: ByteArray, count: Int) { input.write(bytes, 0, count); output.write(bytes, 0, count); afterWrite?.invoke() }
        override fun finish(): Mp3EncodingStats {
            beforeFinish?.invoke()
            if (failingFinish) throw Mp3EncodingException("injected finalization failure")
            return Mp3EncodingStats(input.size().toLong() / 4, input.size().toLong(), 48_000, 192, 2, 1)
        }
        override fun cancel() { cancelled = true }
        override fun close() { closed = true }
    }

    private fun export(
        source: PcmSource = PcmSources.pcm(ByteArrayInputStream(pcm), format),
        destination: File = File(directory.root, "result.mp3"),
        options: Mp3ExportOptions = Mp3ExportOptions(blockFrames = 7, progressIntervalMillis = 0),
        cancellation: Mp3ExportCancellation = Mp3ExportCancellation(),
        observer: Mp3ExportObserver? = null,
        setup: (FakeEncoder) -> Unit = {},
    ): Pair<Mp3ExportResult, FakeEncoder> {
        lateinit var fake: FakeEncoder
        val result = runExport(source, destination, options, cancellation, ExportCallbacks(direct, observer), EncodingFactory { _, _, output ->
            FakeEncoder(output).also { fake = it; setup(it) }
        })
        return result to fake
    }

    private fun noTemporaryFiles() = assertTrue(directory.root.listFiles()!!.none { it.name.endsWith(".part") })

    @Test fun arbitraryPcmFragmentsPreserveEveryByte() {
        val fragmented = object : ByteArrayInputStream(pcm) {
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int = super.read(bytes, offset, minOf(length, 3))
        }
        val (result, fake) = export(PcmSources.pcm(fragmented, format, pcm.size.toLong() / 4))
        assertArrayEquals(pcm, fake.input.toByteArray())
        assertArrayEquals(pcm, result.output.readBytes())
        assertTrue(fake.closed)
        noTemporaryFiles()
    }

    @Test fun wavSkipsOddUnknownChunksAndNeverEncodesHeadersOrTrailingMetadata() {
        val source = PcmSources.wav(ByteArrayInputStream(wavBytes(pcm, oddChunk = true, trailing = true)))
        assertArrayEquals(pcm, export(source).second.input.toByteArray())
    }

    @Test fun monoAndSupportedRatesArePreservedByAdapters() {
        for (rate in listOf(44_100, 48_000, 96_000)) for (channels in 1..2) {
            val expected = PcmFormat(rate, channels)
            PcmSources.wav(ByteArrayInputStream(wavBytes(pcm, expected))).open().use { reader ->
                assertEquals(expected, reader.format)
                assertEquals(pcm.size.toLong() / expected.bytesPerFrame, reader.totalFrames)
            }
        }
    }

    @Test fun streamFactoriesCanRepeatButBorrowedSourcesAreOneShot() {
        val source = PcmSources.wav(InputStreamFactory { ByteArrayInputStream(wavBytes(pcm)) })
        repeat(2) { source.open().close() }
        val once = PcmSources.pcm(ByteArrayInputStream(pcm), format)
        once.open().close()
        assertThrows(Mp3InputException::class.java) { once.open() }
    }

    @Test fun borrowedAndOwnedStreamsHaveExplicitLifetime() {
        class Tracked(bytes: ByteArray) : ByteArrayInputStream(bytes) {
            var closed = false
            override fun close() { closed = true; super.close() }
        }
        val borrowed = Tracked(pcm)
        export(PcmSources.pcm(borrowed, format))
        assertFalse(borrowed.closed)
        val owned = Tracked(pcm)
        export(PcmSources.pcm(owned, format, closeInput = true), File(directory.root, "owned.mp3"))
        assertTrue(owned.closed)
        val malformed = Tracked(byteArrayOf(0))
        assertThrows(Mp3InputException::class.java) { PcmSources.wav(malformed, true).open() }
        assertTrue(malformed.closed)
    }

    @Test fun malformedWavHeadersAndSizesAreRejected() {
        val valid = wavBytes(pcm)
        val malformed = listOf(
            valid.copyOf(11), valid.copyOf().also { it[0] = 'X'.code.toByte() },
            valid.copyOf().also { it[20] = 3 }, // float
            valid.copyOf().also { it[34] = 24 },
            valid.copyOf().also { it[32] = 2 }, // stereo block alignment
            valid.copyOf().also { it[28] = 1 }, // byte rate
            valid.copyOf().also { it[16] = 15 }, // fmt size
            valid.copyOf().also { for (i in 40..43) it[i] = 127 },
            valid.copyOf().also { it[40] = 1 }, // partial frame
        )
        malformed.forEachIndexed { index, bytes ->
            try { PcmSources.wav(ByteArrayInputStream(bytes)).open().close(); fail("Accepted malformed WAV $index") }
            catch (_: Mp3InputException) { }
        }
    }

    @Test fun truncatedPcmAndWavTailFailAndCleanUp() {
        for (bytes in listOf(pcm.copyOf(pcm.size - 1), byteArrayOf())) {
            assertThrows(Mp3InputException::class.java) { export(PcmSources.pcm(ByteArrayInputStream(bytes), format)) }
            noTemporaryFiles()
        }
        val wav = wavBytes(pcm, trailing = true)
        assertThrows(Mp3InputException::class.java) { export(PcmSources.wav(ByteArrayInputStream(wav.copyOf(wav.size - 2)))) }
        assertThrows(Mp3InputException::class.java) { export(PcmSources.wav(ByteArrayInputStream(wav.copyOf(50)))) }
        noTemporaryFiles()
        assertFalse(File(directory.root, "result.mp3").exists())
    }

    @Test fun declaredRawLengthMustMatchExactly() {
        for (frames in listOf(1L, 100_000L)) {
            assertThrows(Mp3InputException::class.java) { export(PcmSources.pcm(ByteArrayInputStream(pcm), format, frames)) }
            noTemporaryFiles()
        }
    }

    @Test fun stalledOrBrokenReadersFailInsteadOfLoopingForever() {
        val stalled = object : InputStream() {
            override fun read(): Int = 0
            override fun read(b: ByteArray, off: Int, len: Int): Int = 0
        }
        assertThrows(Mp3InputException::class.java) { export(PcmSources.pcm(stalled, format)) }
        val broken = object : InputStream() { override fun read(): Int = throw IOException("injected source failure") }
        val failure = assertThrows(Mp3InputException::class.java) { export(PcmSources.pcm(broken, format)) }
        assertTrue(failure.cause is IOException)
        noTemporaryFiles()
    }

    @Test fun cancellationBeforeOpeningDoesNotCreateAnyFile() {
        val token = Mp3ExportCancellation().also { it.cancel() }
        assertThrows(Mp3CancelledException::class.java) { export(PcmSource { error("must not open") }, cancellation = token) }
        assertEquals(0, directory.root.listFiles()!!.size)
    }

    @Test fun cancellationDuringWavHeaderParsingClosesOwnedInput() {
        val token = Mp3ExportCancellation()
        var closed = false
        val stream = object : ByteArrayInputStream(wavBytes(pcm, oddChunk = true)) {
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
                val count = super.read(bytes, offset, length)
                if (pos >= 20) token.cancel()
                return count
            }
            override fun close() { closed = true }
        }
        assertThrows(Mp3CancelledException::class.java) { export(PcmSources.wav(stream, true), cancellation = token) }
        assertTrue(closed)
        assertEquals(0, directory.root.listFiles()!!.size)
    }

    @Test fun partialReadsAreCoalescedIntoBoundedEncoderWrites() {
        var writes = 0
        val fragmented = object : ByteArrayInputStream(pcm) {
            override fun read(bytes: ByteArray, offset: Int, length: Int) = super.read(bytes, offset, minOf(3, length))
        }
        export(PcmSources.pcm(fragmented, format), options = Mp3ExportOptions(blockFrames = 4096)) {
            it.afterWrite = { writes++ }
        }
        assertEquals(2, writes) // One full block and one short final block, despite 3-byte reads.
    }

    @Test fun cancellationDuringWriteReleasesEncoderAndPreservesExistingOutput() {
        val destination = File(directory.root, "existing.mp3").apply { writeText("keep") }
        val token = Mp3ExportCancellation()
        lateinit var fake: FakeEncoder
        assertThrows(Mp3CancelledException::class.java) {
            export(destination = destination, options = Mp3ExportOptions(overwrite = true), cancellation = token) {
                fake = it; it.afterWrite = { token.cancel() }
            }
        }
        assertEquals("keep", destination.readText())
        assertTrue(fake.closed && fake.cancelled)
        noTemporaryFiles()
    }

    @Test fun cancellationDuringFinalizationPreventsCommit() {
        val token = Mp3ExportCancellation()
        assertThrows(Mp3CancelledException::class.java) { export(cancellation = token) { it.beforeFinish = { token.cancel() } } }
        assertFalse(File(directory.root, "result.mp3").exists())
        noTemporaryFiles()
    }

    @Test fun cancellationAtCommitNotificationStillPreventsPublication() {
        val token = Mp3ExportCancellation()
        val observer = object : Mp3ExportObserver() {
            override fun onProgress(progress: Mp3ExportProgress) { if (progress.phase == Mp3ExportPhase.COMMITTING) token.cancel() }
        }
        assertThrows(Mp3CancelledException::class.java) { export(cancellation = token, observer = observer) }
        assertFalse(File(directory.root, "result.mp3").exists())
        noTemporaryFiles()
    }

    @Test fun existingOutputIsProtectedUnlessOverwriteWasExplicit() {
        val file = File(directory.root, "existing.mp3").apply { writeText("keep") }
        assertThrows(Mp3OutputException::class.java) { export(destination = file) }
        assertEquals("keep", file.readText())
        assertThrows(Mp3EncodingException::class.java) {
            export(destination = file, options = Mp3ExportOptions(overwrite = true)) { it.failingFinish = true }
        }
        assertEquals("keep", file.readText())
        export(destination = file, options = Mp3ExportOptions(overwrite = true))
        assertArrayEquals(pcm, file.readBytes())
        noTemporaryFiles()
    }

    @Test fun lateDestinationCollisionDoesNotDeleteTheOtherFile() {
        val file = File(directory.root, "collision.mp3")
        assertThrows(Mp3OutputException::class.java) { export(destination = file) { it.beforeFinish = { file.writeText("other writer") } } }
        assertEquals("other writer", file.readText())
        noTemporaryFiles()
    }

    @Test fun sourceCloseFailurePreventsCommit() {
        val input = object : ByteArrayInputStream(pcm) { override fun close() { throw IOException("close failed") } }
        assertThrows(Mp3InputException::class.java) { export(PcmSources.pcm(input, format, closeInput = true)) }
        assertFalse(File(directory.root, "result.mp3").exists())
        noTemporaryFiles()
        assertThrows(Mp3OutputException::class.java) {
            export { encoder -> encoder.afterWrite = { throw IOException("injected output write failure") } }
        }
        assertFalse(File(directory.root, "result.mp3").exists())
        noTemporaryFiles()
    }

    @Test fun sourceAndDestinationCannotBeTheSameFile() {
        val file = File(directory.root, "input.pcm").apply { writeBytes(pcm) }
        assertThrows(Mp3InputException::class.java) {
            export(PcmSources.pcm(file, format), file, Mp3ExportOptions(overwrite = true))
        }
        assertArrayEquals(pcm, file.readBytes())
    }

    @Test fun progressIsMonotonicAndIncludesFinalization() {
        val events = mutableListOf<Mp3ExportProgress>()
        val token = Mp3ExportCancellation()
        export(PcmSources.pcm(ByteArrayInputStream(pcm), format, pcm.size.toLong() / 4), cancellation = token,
            observer = object : Mp3ExportObserver() { override fun onProgress(progress: Mp3ExportProgress) { events.add(progress) } })
        assertEquals(Mp3ExportPhase.ENCODING, events.first().phase)
        assertTrue(events.zipWithNext().all { (a, b) -> a.inputFrames <= b.inputFrames })
        assertTrue(events.any { it.phase == Mp3ExportPhase.FINALIZING })
        assertEquals(Mp3ExportPhase.COMMITTING, events.last().phase)
        assertEquals(1.0, events.last().inputFraction!!, 0.0)
        assertFalse(token.cancel())
        assertNull(Mp3ExportProgress(1, null, Mp3ExportPhase.ENCODING).inputFraction)
    }

    @Test fun stalledCallbackExecutorHasBoundedQueueAndOneTerminalEvent() {
        val queue = mutableListOf<Runnable>()
        val events = mutableListOf<String>()
        val observer = object : Mp3ExportObserver() {
            override fun onProgress(progress: Mp3ExportProgress) { events.add("p${progress.inputFrames}") }
            override fun onFailure(failure: Throwable) { events.add("failure") }
        }
        val callbacks = ExportCallbacks(Executor { queue.add(it) }, observer)
        repeat(10_000) { callbacks.progress(Mp3ExportProgress(it.toLong(), null, Mp3ExportPhase.ENCODING)) }
        callbacks.failure(IOException("failure"))
        callbacks.failure(IOException("duplicate"))
        assertEquals(1, queue.size)
        queue.single().run()
        assertEquals(listOf("p9999", "failure"), events)
    }

    @Test fun callbackFailuresDoNotTurnSuccessfulAudioIntoFailure() {
        val failures = mutableListOf<Throwable>()
        val callbacks = ExportCallbacks(direct, object : Mp3ExportObserver() {
            override fun onProgress(progress: Mp3ExportProgress) { throw IllegalStateException("UI failed") }
            override fun onFailure(failure: Throwable) { throw AssertionError("terminal observer failed") }
        }, failures::add)
        callbacks.progress(Mp3ExportProgress(0, null, Mp3ExportPhase.ENCODING))
        assertEquals(1, failures.size)
        callbacks.failure(IOException("export failure"))
        callbacks.failure(IOException("duplicate terminal event"))
        assertEquals(2, failures.size)
        assertTrue(failures.last() is AssertionError)
    }

    @Test fun rejectedWorkersAndQueuedCancellationCompleteTheJob() {
        val rejected = Mp3Export.start(PcmSource { error("must not open") }, File(directory.root, "unused"), Executor { throw java.util.concurrent.RejectedExecutionException() })
        assertTrue(rejected.isDone)
        assertThrows(Mp3StateException::class.java) { rejected.await() }
        val queue = mutableListOf<Runnable>()
        val cancelled = Mp3Export.start(PcmSource { error("must not open") }, File(directory.root, "unused"), Executor { queue.add(it) })
        assertFalse(cancelled.isDone)
        cancelled.cancel()
        queue.single().run()
        assertThrows(Mp3CancelledException::class.java) { cancelled.await() }
        assertTrue(cancelled.isDone)
        noTemporaryFiles()
    }

    @Test fun invalidOptionsAndFormatsFailEarly() {
        assertThrows(Mp3ConfigurationException::class.java) { PcmFormat(32_000, 2) }
        assertThrows(Mp3ConfigurationException::class.java) { PcmFormat(48_000, 3) }
        assertThrows(Mp3ConfigurationException::class.java) { Mp3ExportOptions(bitrateKbps = 160) }
        assertThrows(Mp3ConfigurationException::class.java) { Mp3ExportOptions(blockFrames = Int.MAX_VALUE) }
        assertThrows(Mp3ConfigurationException::class.java) { Mp3ExportOptions(progressIntervalMillis = -1) }
        assertThrows(Mp3InputException::class.java) { PcmSources.pcm(ByteArrayInputStream(pcm), format, -1) }
    }
}
