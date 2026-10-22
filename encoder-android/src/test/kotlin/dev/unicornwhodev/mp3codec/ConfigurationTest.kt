// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec

import org.junit.Assert.assertThrows
import org.junit.Test

class ConfigurationTest {
    @Test fun acceptsExactlyThe24SupportedConfigurations() {
        for (rate in listOf(44_100, 48_000, 96_000)) {
            for (channels in 1..2) {
                for (bitrate in listOf(128, 192, 256, 320)) {
                    Mp3EncoderConfig(rate, channels, bitrate).validate()
                }
            }
        }
    }

    @Test fun rejectsUnsupportedParameters() {
        listOf(0, -1, 22_050, 32_000, 88_200, Int.MAX_VALUE).forEach {
            assertThrows(Mp3ConfigurationException::class.java) { Mp3EncoderConfig(it, 1).validate() }
        }
        listOf(-1, 0, 3, Int.MAX_VALUE).forEach {
            assertThrows(Mp3ConfigurationException::class.java) { Mp3EncoderConfig(44_100, it).validate() }
        }
        listOf(0, -1, 64, 160, 321, Int.MAX_VALUE).forEach {
            assertThrows(Mp3ConfigurationException::class.java) { Mp3EncoderConfig(44_100, 1, it).validate() }
        }
    }

    @Test fun validatesSlicesWithoutIntegerOverflow() {
        validateInput(16, 0, 0, 2)
        validateInput(16, 16, 0, 2)
        validateInput(20, 3, 16, 2) // Offset is arbitrary; the selected byte count is frame-aligned.
        listOf(-1 to 2, 0 to -2, 17 to 0, 1 to 16, Int.MAX_VALUE to 2, 1 to Int.MAX_VALUE).forEach { (offset, length) ->
            assertThrows(Mp3InputException::class.java) { validateInput(16, offset, length, 2) }
        }
        assertThrows(Mp3InputException::class.java) { validateInput(16, 0, 2, 2) }
        assertThrows(Mp3InputException::class.java) { validateInput(16, 0, 1, 1) }
    }
}
