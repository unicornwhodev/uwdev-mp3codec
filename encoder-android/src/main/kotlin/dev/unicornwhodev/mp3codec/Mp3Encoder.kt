// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec

import android.os.Looper
import java.io.OutputStream

/**
 * An offline streaming encoder. Use on a worker thread and always close/use it.
 * This object never closes or flushes the caller's OutputStream.
 * Only cancel() and close() may run concurrently with write/finish.
 * Cancellation cannot forcibly interrupt a blocking caller-owned OutputStream.
 */
class Mp3Encoder private constructor(
    private val config: Mp3EncoderConfig,
    private var nativeHandle: Long,
) : AutoCloseable {
    private enum class State { OPEN, FINISHED, CANCELLED, CLOSED, FAILED }
    private val lock = Any()
    private var state = State.OPEN
    private var operationActive = false
    private var completedStats: Mp3EncodingStats? = null

    companion object {
        @JvmStatic
        fun open(config: Mp3EncoderConfig, output: OutputStream): Mp3Encoder {
            config.validate()
            val handle = try {
                NativeBridge.create(config.inputSampleRate, config.channels, config.bitrateKbps, OutputAdapter(output))
            } catch (e: LinkageError) {
                throw Mp3NativeException("The Android native encoder could not be loaded for this ABI", e)
            }
            if (handle == 0L) throw Mp3NativeException("Native creation returned an invalid handle")
            return try {
                Mp3Encoder(config, handle)
            } catch (failure: Throwable) {
                NativeBridge.destroy(handle)
                throw failure
            }
        }

        private fun requireWorkerThread() {
            val current = Looper.myLooper()
            if (current != null && current === Looper.getMainLooper()) {
                throw Mp3StateException("PCM encoding and finalization must run off the Android main thread")
            }
        }
    }

    @JvmOverloads
    fun writePcm16Le(data: ByteArray, offset: Int = 0, length: Int = data.size - offset) {
        requireWorkerThread()
        validateInput(data.size, offset, length, config.channels)
        perform({ handle -> NativeBridge.write(handle, data, offset, length) })
    }

    fun finish(): Mp3EncodingStats {
        synchronized(lock) { completedStats?.let { return it } }
        requireWorkerThread()
        return perform(
            nativeCall = { handle ->
                val values = NativeBridge.finish(handle)
                if (values.size != 9) throw Mp3NativeException("Malformed native statistics")
                Mp3EncodingStats(values[0], values[1], values[2].toInt(), values[3].toInt(), values[4].toInt(), values[5]).also {
                    it.peakProtection = Mp3PeakProtectionInfo(Double.fromBits(values[6]), values[7], Double.fromBits(values[8]))
                }
            },
            onSuccess = { stats ->
                completedStats = stats
                state = State.FINISHED
            },
        )
    }

    /** Signal cancellation promptly. In-flight native resources are released by that operation. */
    fun cancel() {
        synchronized(lock) {
            if (state != State.OPEN) return
            state = State.CANCELLED
            NativeBridge.cancel(nativeHandle)
            if (!operationActive) releaseLocked()
        }
    }

    /** Discard unfinished output; this does not implicitly finish an export. */
    override fun close() {
        synchronized(lock) {
            if (state == State.CLOSED) return
            if (state == State.OPEN) NativeBridge.cancel(nativeHandle)
            if (state != State.CANCELLED && state != State.FAILED) state = State.CLOSED
            if (!operationActive) releaseLocked()
        }
    }

    private fun checkOpenLocked() {
        when (state) {
            State.OPEN -> Unit
            State.CANCELLED -> throw Mp3CancelledException()
            else -> throw Mp3StateException("Encoder is ${state.name.lowercase()}")
        }
    }

    private fun <T> perform(nativeCall: (Long) -> T, onSuccess: (T) -> Unit = {}): T {
        val handle = synchronized(lock) {
            checkOpenLocked()
            if (operationActive) throw Mp3StateException("Concurrent write/finish calls are not supported")
            operationActive = true
            nativeHandle
        }
        try {
            val result = nativeCall(handle)
            synchronized(lock) {
                checkOpenLocked()
                onSuccess(result)
            }
            return result
        } catch (failure: Throwable) {
            synchronized(lock) { if (state == State.OPEN) state = State.FAILED }
            throw failure
        } finally {
            synchronized(lock) {
                operationActive = false
                if (state != State.OPEN) releaseLocked()
            }
        }
    }

    private fun releaseLocked() {
        val handle = nativeHandle
        nativeHandle = 0
        if (handle != 0L) NativeBridge.destroy(handle)
    }

    private class OutputAdapter(private val target: OutputStream) : OutputStream() {
        override fun write(value: Int) = write(byteArrayOf(value.toByte()), 0, 1)
        override fun write(data: ByteArray, offset: Int, length: Int) {
            try {
                target.write(data, offset, length)
            } catch (failure: Exception) {
                throw Mp3OutputException("The output stream rejected encoded audio", failure)
            }
        }
    }
}

internal fun validateInput(size: Int, offset: Int, length: Int, channels: Int) {
    // Subtraction keeps validation correct even when offset + length would overflow Int.
    if (offset < 0 || length < 0 || offset > size || length > size - offset) {
        throw Mp3InputException("PCM offset/length is outside the byte array")
    }
    if (length % (channels * 2) != 0) {
        throw Mp3InputException("Each PCM block must contain whole interleaved 16-bit frames")
    }
}
