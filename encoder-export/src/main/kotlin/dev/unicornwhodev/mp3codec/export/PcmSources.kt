// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export

import dev.unicornwhodev.mp3codec.Mp3ConfigurationException
import dev.unicornwhodev.mp3codec.Mp3InputException
import java.io.File
import java.io.InputStream
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

/** Signed, interleaved PCM16LE. No normalization, channel mixing or rate conversion is performed here. */
data class PcmFormat(val sampleRate: Int, val channels: Int) {
    init {
        if (sampleRate !in listOf(44_100, 48_000, 96_000) || channels !in 1..2) {
            throw Mp3ConfigurationException("Expected PCM16LE at 44100, 48000 or 96000 Hz, mono or stereo")
        }
    }
    val bytesPerFrame: Int get() = channels * 2
}

/** The returned stream is owned and closed by the adapter, including when header parsing fails. */
fun interface InputStreamFactory { @Throws(IOException::class) fun open(): InputStream }

/** Open a fresh reader for each export; custom renderers can implement this interface. */
fun interface PcmSource { @Throws(IOException::class) fun open(): PcmReader }

interface PcmReader : AutoCloseable {
    val format: PcmFormat
    /** Exact frame count, or null when the source length is unknown. */
    val totalFrames: Long?
    /** Same contract as InputStream.read. Byte fragments need not be PCM-frame aligned. */
    @Throws(IOException::class) fun read(buffer: ByteArray, offset: Int, length: Int): Int
    @Throws(IOException::class) override fun close()
}

internal open class AdapterSource(private val factory: (check: () -> Unit) -> PcmReader) : PcmSource {
    override fun open(): PcmReader = factory {}
    fun open(check: () -> Unit): PcmReader = factory(check)
}

internal class FileSource(val file: File, factory: (check: () -> Unit) -> PcmReader) : AdapterSource(factory)

private fun checked(input: InputStream, check: () -> Unit): InputStream = object : InputStream() {
    override fun read(): Int { check(); return input.read().also { check() } }
    override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
        check(); return input.read(bytes, offset, length).also { check() }
    }
    override fun close() = input.close()
}

object PcmSources {
    @JvmStatic fun pcm(file: File, format: PcmFormat): PcmSource = FileSource(file) { check ->
        val input = file.inputStream()
        try {
            val bytes = input.channel.size()
            if (bytes % format.bytesPerFrame != 0L) throw Mp3InputException("PCM file ends inside a channel frame")
            RawReader(checked(input, check), format, bytes / format.bytesPerFrame, true)
        } catch (failure: Throwable) {
            try { input.close() } catch (closing: Throwable) { failure.addSuppressed(closing) }
            throw failure
        }
    }

    @JvmStatic @JvmOverloads
    fun pcm(format: PcmFormat, factory: InputStreamFactory, totalFrames: Long? = null): PcmSource {
        requireFrameCount(totalFrames)
        return AdapterSource { check -> RawReader(checked(factory.open(), check), format, totalFrames, true) }
    }

    /** One-shot source. Borrowed streams remain open by default, including on failure. */
    @JvmStatic @JvmOverloads
    fun pcm(input: InputStream, format: PcmFormat, totalFrames: Long? = null, closeInput: Boolean = false): PcmSource {
        requireFrameCount(totalFrames)
        return once { check -> RawReader(checked(input, check), format, totalFrames, closeInput) }
    }

    @JvmStatic fun wav(file: File): PcmSource = FileSource(file) { check -> WavReader.open(checked(file.inputStream(), check), true) }
    @JvmStatic fun wav(factory: InputStreamFactory): PcmSource = AdapterSource { check -> WavReader.open(checked(factory.open(), check), true) }

    @JvmStatic @JvmOverloads
    fun wav(input: InputStream, closeInput: Boolean = false): PcmSource = once { check -> WavReader.open(checked(input, check), closeInput) }

    private fun once(open: (check: () -> Unit) -> PcmReader): PcmSource {
        val used = AtomicBoolean()
        return AdapterSource { check ->
            if (!used.compareAndSet(false, true)) throw Mp3InputException("This stream source has already been opened; use a stream factory to repeat an export")
            open(check)
        }
    }

    private fun requireFrameCount(count: Long?) {
        if (count != null && count < 0) throw Mp3InputException("totalFrames must be non-negative")
    }
}

private class RawReader(
    private val input: InputStream,
    override val format: PcmFormat,
    override val totalFrames: Long?,
    private val closeInput: Boolean,
) : PcmReader {
    override fun read(buffer: ByteArray, offset: Int, length: Int): Int = input.read(buffer, offset, length)
    override fun close() { if (closeInput) input.close() }
}
