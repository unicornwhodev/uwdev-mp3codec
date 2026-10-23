// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export;

import dev.unicornwhodev.mp3codec.Mp3CancelledException;
import org.junit.Test;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.util.ArrayList;
import static org.junit.Assert.*;

public class JavaApiTest {
    @Test public void javaFactoriesAllowCheckedIoAndAsyncCancellation() {
        PcmSource reopenable = PcmSources.wav(() -> new FileInputStream("input.wav"));
        assertNotNull(reopenable);
        PcmSource source = PcmSources.pcm(new ByteArrayInputStream(new byte[4]), new PcmFormat(48000, 2));
        ArrayList<Runnable> work = new ArrayList<>();
        Mp3ExportJob job = Mp3Export.start(source, new File("unused.mp3"), work::add, new Mp3ExportOptions(256));
        assertTrue(job.cancel());
        work.get(0).run();
        assertThrows(Mp3CancelledException.class, job::await);
        assertTrue(job.isDone());
    }
}
