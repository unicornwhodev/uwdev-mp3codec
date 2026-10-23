// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export

import dev.unicornwhodev.mp3codec.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

enum class Mp3Preset(val bitrateKbps: Int) {
    COMPACT_128(128), BALANCED_192(192), HIGH_256(256), MAXIMUM_320(320)
}

data class Mp3ExportOptions @JvmOverloads constructor(
    val bitrateKbps: Int = 192,
    val blockFrames: Int = 4096,
    val overwrite: Boolean = false,
    val progressIntervalMillis: Long = 100,
) {
    init {
        if (bitrateKbps !in listOf(128, 192, 256, 320)) throw Mp3ConfigurationException("Unsupported CBR bitrate")
        if (blockFrames !in 1..65_536) throw Mp3ConfigurationException("blockFrames must be between 1 and 65536")
        if (progressIntervalMillis !in 0..60_000) throw Mp3ConfigurationException("progressIntervalMillis must be between 0 and 60000")
    }
}

enum class Mp3ExportPhase { ENCODING, FINALIZING, COMMITTING }

data class Mp3ExportProgress(val inputFrames: Long, val totalFrames: Long?, val phase: Mp3ExportPhase) {
    /** Input consumption only. 1.0 is not a successful file commit; wait for onSuccess. */
    val inputFraction: Double? get() = totalFrames?.takeIf { it > 0 }?.let { (inputFrames.toDouble() / it).coerceIn(0.0, 1.0) }
}

data class Mp3ExportResult(val output: File, val format: PcmFormat, val statistics: Mp3EncodingStats)

/** Callbacks use the supplied callback executor (or the worker by default), in order. */
abstract class Mp3ExportObserver {
    open fun onProgress(progress: Mp3ExportProgress) {}
    open fun onSuccess(result: Mp3ExportResult) {}
    open fun onFailure(failure: Throwable) {}
}

/** One export per token. Cancellation is cooperative; blocking external I/O cannot be forcibly interrupted. */
class Mp3ExportCancellation {
    private val lock = Any()
    private var claimed = false
    private var cancelled = false
    private var committing = false
    private var done = false
    private var encoder: EncodingSession? = null

    val isCancellationRequested: Boolean get() = synchronized(lock) { cancelled }

    /** Returns false once commit has started or the export has completed. Never undoes a successful export. */
    fun cancel(): Boolean {
        val active = synchronized(lock) {
            if (committing || done) return false
            cancelled = true
            encoder
        }
        active?.cancel()
        return true
    }
    internal fun claim() = synchronized(lock) {
        if (claimed) throw Mp3StateException("A cancellation token belongs to one export only")
        claimed = true
    }
    internal fun check() { if (isCancellationRequested) throw Mp3CancelledException() }
    internal fun bind(value: EncodingSession) {
        val cancelNow = synchronized(lock) { encoder = value; cancelled }
        if (cancelNow) value.cancel()
        check()
    }
    internal fun unbind() = synchronized(lock) { encoder = null }
    internal fun beginCommit() = synchronized(lock) {
        if (cancelled) throw Mp3CancelledException()
        committing = true
    }
    internal fun complete() = synchronized(lock) { encoder = null; done = true }
}

/** await() completes only after streams are closed and temporary-file cleanup has been attempted. */
class Mp3ExportJob internal constructor(internal val cancellation: Mp3ExportCancellation) {
    private val finished = CountDownLatch(1)
    @Volatile private var result: Mp3ExportResult? = null
    @Volatile private var failure: Throwable? = null
    @Volatile var callbackFailure: Throwable? = null
        internal set
    val isDone: Boolean get() = finished.count == 0L
    fun cancel(): Boolean = cancellation.cancel()

    @Throws(InterruptedException::class)
    fun await(): Mp3ExportResult { finished.await(); return outcome() }

    @Throws(InterruptedException::class, TimeoutException::class)
    fun await(timeout: Long, unit: TimeUnit): Mp3ExportResult {
        if (!finished.await(timeout, unit)) throw TimeoutException("Export is still running")
        return outcome()
    }
    private fun outcome(): Mp3ExportResult { failure?.let { throw it }; return checkNotNull(result) }
    internal fun succeed(value: Mp3ExportResult) { result = value; finished.countDown() }
    internal fun fail(value: Throwable) { failure = value; finished.countDown() }
}
