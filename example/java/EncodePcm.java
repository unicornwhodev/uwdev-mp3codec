// SPDX-License-Identifier: MIT
import dev.unicornwhodev.mp3codec.export.*;
import java.io.File;

public final class EncodePcm {
    // Blocking example: call on a worker thread. The source contains raw PCM, not a WAV header.
    public static Mp3ExportResult encode(File input, File output) {
        PcmSource source = PcmSources.pcm(input, new PcmFormat(48000, 2));
        return Mp3Export.encode(source, output, new Mp3ExportOptions(256));
    }
}
