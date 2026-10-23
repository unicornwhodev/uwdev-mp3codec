// SPDX-License-Identifier: MIT
import dev.unicornwhodev.mp3codec.export.*
import java.io.File

// Blocking example: call on a worker thread. See docs/EXPORT.md for async jobs.
fun encodeWav(input: File, output: File): Mp3ExportResult =
    Mp3Export.fromWav(input, output, Mp3Preset.HIGH_256)
