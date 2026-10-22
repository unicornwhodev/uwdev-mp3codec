// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec

import java.io.OutputStream

internal object NativeBridge {
    init {
        System.loadLibrary("uwdev_mp3codec")
    }

    @JvmStatic external fun create(sampleRate: Int, channels: Int, bitrateKbps: Int, output: OutputStream): Long
    @JvmStatic external fun write(handle: Long, data: ByteArray, offset: Int, length: Int)
    @JvmStatic external fun finish(handle: Long): LongArray
    @JvmStatic external fun cancel(handle: Long)
    @JvmStatic external fun destroy(handle: Long)
}
