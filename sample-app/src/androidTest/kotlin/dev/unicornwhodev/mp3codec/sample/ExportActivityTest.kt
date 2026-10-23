// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.sample

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.Spinner
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.TimeUnit
import kotlin.math.PI
import kotlin.math.sin

@RunWith(AndroidJUnit4::class)
class ExportActivityTest {
    @Test fun releaseExampleExportsPlaysSavesAndCancels() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val source = File(context.cacheDir, "sample-test.wav")
        val frames = 48_000 * 3
        val pcm = ByteArray(frames * 2) { 0 }
        for (frame in 0 until frames) {
            val sample = (sin(2 * PI * 440 * frame / 48_000) * 6000).toInt()
            pcm[frame * 2] = sample.toByte(); pcm[frame * 2 + 1] = (sample shr 8).toByte()
        }
        fun le(value: Int, count: Int) = ByteArray(count) { (value shr (8 * it)).toByte() }
        source.writeBytes("RIFF".toByteArray() + le(36 + pcm.size, 4) + "WAVEfmt ".toByteArray() + le(16, 4) +
            le(1, 2) + le(1, 2) + le(48_000, 4) + le(96_000, 4) + le(2, 2) + le(16, 2) + "data".toByteArray() + le(pcm.size, 4) + pcm)
        val activity = instrumentation.startActivitySync(Intent(context, ExportActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as ExportActivity
        fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
        fun all() = views(activity.window.decorView)
        fun button(name: String) = all().filterIsInstance<Button>().single { it.text.toString() == name }
        fun status(): String = all().filterIsInstance<TextView>().filterNot { it is Button }.joinToString("\n") { it.text }
        fun awaitStatus(expected: String) {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15)
            var current = ""
            while (System.nanoTime() < deadline) {
                instrumentation.runOnMainSync { current = status() }
                if (current.contains(expected)) return
                Thread.sleep(20)
            }
            fail("Expected '$expected', actual UI: $current")
        }
        fun deliverDocument(request: Int, file: File) {
            val callback = ExportActivity::class.java.getDeclaredMethod("onActivityResult", Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, Intent::class.java)
            callback.isAccessible = true
            callback.invoke(activity, request, Activity.RESULT_OK, Intent().setData(Uri.fromFile(file)))
        }
        try {
            val directory = File(context.filesDir, "exports").apply { mkdirs() }
            val before = directory.listFiles()!!.map { it.name }.toSet()
            instrumentation.runOnMainSync {
                assertFalse(button("Export MP3").isEnabled)
                deliverDocument(1, source)
                all().filterIsInstance<Spinner>().single().setSelection(2)
                button("Export MP3").performClick()
            }
            awaitStatus("Export complete:")
            val produced = directory.listFiles()!!.single { it.name !in before }
            assertTrue(produced.length() > 0)
            instrumentation.runOnMainSync { assertTrue(status().contains("256 kbit/s")); button("Play MP3").performClick() }
            awaitStatus("Playback completed.")
            val copy = File(context.cacheDir, "sample-test-copy.mp3")
            instrumentation.runOnMainSync { deliverDocument(2, copy) }
            awaitStatus("MP3 copy saved.")
            assertArrayEquals(produced.readBytes(), copy.readBytes())
            val afterSuccess = directory.listFiles()!!.map { it.name }.toSet()
            instrumentation.runOnMainSync { button("Export MP3").performClick(); button("Cancel export").performClick() }
            awaitStatus("Export cancelled.")
            assertEquals(afterSuccess, directory.listFiles()!!.map { it.name }.toSet())
            assertTrue(directory.listFiles()!!.none { it.name.endsWith(".part") })
            instrumentation.runOnMainSync { button("Use bundled WAV sample").performClick() }
            awaitStatus("Bundled stereo WAV loaded.")
            instrumentation.runOnMainSync { button("Export MP3").performClick() }
            awaitStatus("Export complete: 96000 frames")
            instrumentation.runOnMainSync { button("Play MP3").performClick() }
            awaitStatus("Playback completed.")
            File(context.getExternalFilesDir(null), "export-ui-validation.json").writeText(
                """{"status":"PASS","release_r8":true,"wav_export":true,"bitrate_kbps":256,"playback_to_end":true,"copy_identical":true,"cancellation_cleanup":true,"bundled_sample_export":true}""")
        } finally { instrumentation.runOnMainSync { activity.finish() } }
    }
}
