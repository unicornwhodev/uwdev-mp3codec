// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export

import android.os.Looper
import dev.unicornwhodev.mp3codec.*
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.concurrent.Executor

internal interface EncodingSession : AutoCloseable {
    fun write(bytes: ByteArray, count: Int)
    fun finish(): Mp3EncodingStats
    fun cancel()
}

internal fun interface EncodingFactory {
    fun open(format: PcmFormat, bitrate: Int, output: OutputStream): EncodingSession
}

private val qualifiedEncoder = EncodingFactory { format, bitrate, output ->
    val core = Mp3Encoder.open(Mp3EncoderConfig(format.sampleRate, format.channels, bitrate), output)
    object : EncodingSession {
        override fun write(bytes: ByteArray, count: Int) = core.writePcm16Le(bytes, 0, count)
        override fun finish() = core.finish()
        override fun cancel() = core.cancel()
        override fun close() = core.close()
    }
}

object Mp3Export {
    /** Blocking API: call on a worker thread. The parent directory must already exist. */
    @JvmStatic @JvmOverloads
    fun encode(
        source: PcmSource,
        output: File,
        options: Mp3ExportOptions = Mp3ExportOptions(),
        cancellation: Mp3ExportCancellation = Mp3ExportCancellation(),
        observer: Mp3ExportObserver? = null,
    ): Mp3ExportResult {
        val callbacks = ExportCallbacks(Executor { it.run() }, observer)
        return try {
            runExport(source, output, options, cancellation, callbacks, qualifiedEncoder).also { callbacks.success(it) }
        } catch (failure: Throwable) { callbacks.failure(failure); throw failure }
    }

    @JvmStatic @JvmOverloads
    fun fromWav(input: File, output: File, preset: Mp3Preset = Mp3Preset.BALANCED_192): Mp3ExportResult =
        encode(PcmSources.wav(input), output, Mp3ExportOptions(preset.bitrateKbps))

    /** Uses caller-owned executors; no global thread pool, Activity or CoroutineScope is retained. */
    @JvmStatic @JvmOverloads
    fun start(
        source: PcmSource,
        output: File,
        worker: Executor,
        options: Mp3ExportOptions = Mp3ExportOptions(),
        callbackExecutor: Executor = Executor { it.run() },
        observer: Mp3ExportObserver? = null,
    ): Mp3ExportJob {
        val job = Mp3ExportJob(Mp3ExportCancellation())
        val callbacks = ExportCallbacks(callbackExecutor, observer) { job.callbackFailure = it }
        try {
            worker.execute {
                try {
                    val result = runExport(source, output, options, job.cancellation, callbacks, qualifiedEncoder)
                    job.succeed(result)
                    callbacks.success(result)
                } catch (failure: Throwable) {
                    job.fail(failure)
                    callbacks.failure(failure)
                }
            }
        } catch (failure: Exception) {
            job.cancellation.complete()
            val error = Mp3StateException("The worker executor rejected the export", failure)
            job.fail(error)
            callbacks.failure(error)
        }
        return job
    }
}

internal fun runExport(
    source: PcmSource, output: File, options: Mp3ExportOptions,
    cancellation: Mp3ExportCancellation, callbacks: ExportCallbacks, factory: EncodingFactory,
): Mp3ExportResult {
    cancellation.claim()
    var temporary: File? = null
    var primaryFailure: Throwable? = null
    try {
        cancellation.check()
        val looper = Looper.myLooper()
        if (looper != null && looper === Looper.getMainLooper()) throw Mp3StateException("Use Mp3Export.start or call encode on a worker thread")
        val destination = output.absoluteFile
        val parent = destination.parentFile
        if (parent == null || !parent.isDirectory) throw Mp3OutputException("The destination parent must be an existing directory")
        if (destination.isDirectory || (destination.exists() && !options.overwrite)) throw Mp3OutputException("Destination already exists; choose another file or explicitly enable overwrite")
        if (source is FileSource && source.file.canonicalFile == destination.canonicalFile) throw Mp3InputException("Input and output must be different files")
        val reader = inputOperation { if (source is AdapterSource) source.open { cancellation.check() } else source.open() }
        val result = reader.use {
            cancellation.check()
            val format = reader.format
            val total = reader.totalFrames
            if (total != null && total < 0) throw Mp3InputException("Source totalFrames must be non-negative")
            temporary = try { File.createTempFile(".uwdev-", ".part", parent) }
            catch (failure: IOException) { throw Mp3OutputException("Cannot create the temporary export", failure) }
            val stats = try {
                checkNotNull(temporary).outputStream().buffered().use { stream ->
                    factory.open(format, options.bitrateKbps, stream).use { encoder ->
                        try {
                            cancellation.bind(encoder)
                            copyPcm(reader, encoder, options, cancellation, callbacks)
                        } finally { cancellation.unbind() }
                    }
                }
            } catch (failure: IOException) { throw Mp3OutputException("Cannot write or close the temporary export", failure) }
            Mp3ExportResult(destination, format, stats)
        }
        cancellation.check()
        callbacks.progress(Mp3ExportProgress(result.statistics.inputFrames, reader.totalFrames, Mp3ExportPhase.COMMITTING))
        cancellation.beginCommit()
        try {
            if (options.overwrite) {
                // Do not fall back to a non-atomic overwrite: existing output must survive a failed replacement.
                Files.move(checkNotNull(temporary).toPath(), destination.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } else Files.move(checkNotNull(temporary).toPath(), destination.toPath())
        } catch (failure: IOException) { throw Mp3OutputException("Cannot commit the completed export", failure) }
        temporary = null
        return result
    } catch (failure: Throwable) {
        val reported = if (failure is IOException) Mp3InputException("Cannot read or close the audio source", failure) else failure
        primaryFailure = reported
        throw reported
    } finally {
        try {
            temporary?.let { file ->
                try { Files.deleteIfExists(file.toPath()) }
                catch (failure: IOException) {
                    val cleanup = Mp3OutputException("Temporary export cleanup failed: ${file.name}", failure)
                    if (primaryFailure != null) primaryFailure.addSuppressed(cleanup) else throw cleanup
                }
            }
        } finally { cancellation.complete() }
    }
}

private inline fun <T> inputOperation(action: () -> T): T = try { action() }
catch (failure: IOException) { throw Mp3InputException("Cannot read the audio source", failure) }

private fun copyPcm(
    reader: PcmReader, encoder: EncodingSession, options: Mp3ExportOptions,
    cancellation: Mp3ExportCancellation, callbacks: ExportCallbacks,
): Mp3EncodingStats {
    val frameBytes = reader.format.bytesPerFrame
    val buffer = ByteArray(options.blockFrames * frameBytes)
    var buffered = 0
    var frames = 0L
    var emptyReads = 0
    var lastNotice = System.nanoTime()
    callbacks.progress(Mp3ExportProgress(0, reader.totalFrames, Mp3ExportPhase.ENCODING))
    while (true) {
        cancellation.check()
        val capacity = buffer.size - buffered
        val count = inputOperation { reader.read(buffer, buffered, capacity) }
        if (count < -1 || count > capacity) throw Mp3InputException("Source returned an invalid byte count")
        if (count == -1 && buffered % frameBytes != 0) throw Mp3InputException("PCM source ends inside a channel frame")
        if (count == -1 && buffered == 0) break
        if (count == 0) {
            if (++emptyReads >= 16) throw Mp3InputException("Source made no progress for 16 consecutive reads")
            continue
        }
        emptyReads = 0
        if (count > 0) buffered += count
        // Coalesce fragmented streams before JNI; never encode a whole file in one allocation.
        if (buffered < buffer.size && count != -1) continue
        val aligned = buffered
        if (aligned > 0) {
            cancellation.check()
            val added = aligned / frameBytes
            if (frames > Long.MAX_VALUE - added) throw Mp3InputException("PCM frame count overflow")
            frames += added
            if (reader.totalFrames?.let { frames > it } == true) throw Mp3InputException("Source exceeds its declared frame count")
            encoder.write(buffer, aligned)
            buffered = 0
            val now = System.nanoTime()
            if (now - lastNotice >= options.progressIntervalMillis * 1_000_000) {
                callbacks.progress(Mp3ExportProgress(frames, reader.totalFrames, Mp3ExportPhase.ENCODING))
                lastNotice = now
            }
        }
        if (count == -1) break
    }
    if (buffered != 0) throw Mp3InputException("PCM source ends inside a channel frame")
    if (frames == 0L) throw Mp3InputException("Audio source contains no PCM frames")
    if (reader.totalFrames?.let { frames != it } == true) throw Mp3InputException("Source ended before its declared frame count")
    cancellation.check()
    callbacks.progress(Mp3ExportProgress(frames, reader.totalFrames, Mp3ExportPhase.FINALIZING))
    cancellation.check()
    return encoder.finish().also {
        if (it.inputFrames != frames) throw Mp3EncodingException("Encoder and source frame counts disagree")
    }
}
