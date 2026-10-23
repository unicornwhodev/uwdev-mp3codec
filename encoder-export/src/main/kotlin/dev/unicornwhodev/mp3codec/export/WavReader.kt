// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export

import dev.unicornwhodev.mp3codec.Mp3InputException
import java.io.InputStream

/** Bounded RIFF parser: honors chunk sizes, odd padding and data boundaries; never buffers a file. */
internal class WavReader private constructor(
    private val input: InputStream,
    private val closeInput: Boolean,
) : PcmReader {
    override lateinit var format: PcmFormat
        private set
    override var totalFrames: Long? = null
        private set
    private var riffRemaining = 0L
    private var dataRemaining = 0L
    private var dataPadding = 0L
    private var finished = false
    private val scratch = ByteArray(8192)

    companion object {
        fun open(input: InputStream, closeInput: Boolean): WavReader {
            val reader = WavReader(input, closeInput)
            try { reader.header(); return reader }
            catch (failure: Throwable) {
                try { reader.close() } catch (closing: Throwable) { failure.addSuppressed(closing) }
                throw failure
            }
        }
    }

    private fun invalid(message: String): Nothing = throw Mp3InputException(message)
    private fun exact(size: Int): ByteArray = ByteArray(size).also { bytes ->
        var position = 0
        while (position < size) {
            val count = input.read(bytes, position, size - position)
            if (count < 0) invalid("Truncated WAV header or chunk")
            if (count == 0) {
                val byte = input.read()
                if (byte < 0) invalid("Truncated WAV header or chunk")
                bytes[position++] = byte.toByte()
            } else position += count
        }
    }
    private fun skip(size: Long) {
        var remaining = size
        while (remaining > 0) {
            val count = input.read(scratch, 0, minOf(remaining, scratch.size.toLong()).toInt())
            if (count < 0) invalid("Truncated WAV chunk")
            if (count == 0) {
                if (input.read() < 0) invalid("Truncated WAV chunk")
                remaining--
            } else remaining -= count
        }
    }
    private fun u16(bytes: ByteArray, start: Int) =
        (bytes[start].toInt() and 255) or ((bytes[start + 1].toInt() and 255) shl 8)
    private fun u32(bytes: ByteArray, start: Int): Long =
        (0..3).fold(0L) { value, i -> value or ((bytes[start + i].toLong() and 255) shl (8 * i)) }
    private fun tag(bytes: ByteArray, start: Int = 0) = String(bytes, start, 4, Charsets.US_ASCII)

    private fun chunk(): Pair<String, Long> {
        if (riffRemaining < 8) invalid("WAV chunk header exceeds RIFF boundary")
        val bytes = exact(8)
        riffRemaining -= 8
        val size = u32(bytes, 4)
        if (size + (size and 1) > riffRemaining) invalid("WAV chunk exceeds RIFF boundary")
        return tag(bytes) to size
    }

    private fun header() {
        val header = exact(12)
        if (tag(header) != "RIFF" || tag(header, 8) != "WAVE") invalid("Expected a little-endian RIFF/WAVE file (RF64 and RIFX are unsupported)")
        riffRemaining = u32(header, 4) - 4
        if (riffRemaining < 0) invalid("Invalid RIFF size")
        var foundFormat = false
        while (riffRemaining > 0) {
            val (id, size) = chunk()
            when (id) {
                "fmt " -> {
                    if (foundFormat || size < 16) invalid("Missing or duplicate WAV format")
                    val fields = exact(16)
                    if (u16(fields, 0) != 1 || u16(fields, 14) != 16) invalid("Only uncompressed WAV PCM16 is supported; float and extensible WAV are unsupported")
                    format = PcmFormat(u32(fields, 4).let {
                        if (it > Int.MAX_VALUE) invalid("Invalid WAV sample rate")
                        it.toInt()
                    }, u16(fields, 2))
                    if (u16(fields, 12) != format.bytesPerFrame || u32(fields, 8) != format.sampleRate.toLong() * format.bytesPerFrame) invalid("Inconsistent WAV byte rate or block alignment")
                    skip(size - 16 + (size and 1))
                    riffRemaining -= size + (size and 1)
                    foundFormat = true
                }
                "data" -> {
                    if (!foundFormat) invalid("WAV data precedes its format")
                    if (size % format.bytesPerFrame != 0L) invalid("WAV data ends inside a PCM frame")
                    dataRemaining = size
                    dataPadding = size and 1
                    totalFrames = size / format.bytesPerFrame
                    riffRemaining -= size + dataPadding
                    return
                }
                else -> { skip(size + (size and 1)); riffRemaining -= size + (size and 1) }
            }
        }
        invalid("WAV data chunk is missing")
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        if (offset < 0 || length < 0 || offset > buffer.size || length > buffer.size - offset) throw IndexOutOfBoundsException()
        if (length == 0) return 0
        if (dataRemaining > 0) {
            val count = input.read(buffer, offset, minOf(dataRemaining, length.toLong()).toInt())
            if (count < 0) invalid("Truncated WAV PCM data")
            if (count > 0) dataRemaining -= count
            return count
        }
        if (!finished) {
            skip(dataPadding)
            while (riffRemaining > 0) {
                val (id, size) = chunk()
                if (id == "data" || id == "fmt ") invalid("Multiple WAV data or format chunks are unsupported")
                skip(size + (size and 1)); riffRemaining -= size + (size and 1)
            }
            finished = true
        }
        return -1
    }

    override fun close() { if (closeInput) input.close() }
}
