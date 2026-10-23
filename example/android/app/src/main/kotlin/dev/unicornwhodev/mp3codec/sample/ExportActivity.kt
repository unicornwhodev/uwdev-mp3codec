// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.sample

import android.app.Activity
import android.content.Intent
import android.media.MediaPlayer
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.widget.*
import dev.unicornwhodev.mp3codec.export.*
import java.io.File
import java.util.UUID
import java.util.concurrent.Executor
import java.util.concurrent.Executors

/** Complete integration: choose a WAV, export with progress/cancellation, play, and save a copy. */
class ExportActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val ui = Executor { action -> runOnUiThread { if (!isDestroyed) action.run() } }
    private var job: Mp3ExportJob? = null
    private var input: Uri? = null
    private var exported: File? = null
    private var player: MediaPlayer? = null
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private lateinit var bitrate: Spinner
    private lateinit var pick: Button
    private lateinit var demo: Button
    private lateinit var start: Button
    private lateinit var cancel: Button
    private lateinit var play: Button
    private lateinit var save: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val column = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 48, 32, 24) }
        column.addView(TextView(this).apply { text = "WAV → MP3 export"; textSize = 24f })
        status = TextView(this).apply { text = "Choose a PCM16 WAV (44.1, 48 or 96 kHz; mono or stereo)." }
        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 1000 }
        bitrate = Spinner(this).apply {
            adapter = ArrayAdapter(this@ExportActivity, android.R.layout.simple_spinner_dropdown_item, arrayOf("128 kbit/s", "192 kbit/s", "256 kbit/s", "320 kbit/s"))
            setSelection(1)
        }
        fun button(label: String, action: () -> Unit): Button = Button(this).apply {
            text = label; setOnClickListener { action() }; column.addView(this)
        }
        column.addView(status); column.addView(bitrate); column.addView(progress)
        pick = button("Choose WAV") {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                type = "audio/*"; addCategory(Intent.CATEGORY_OPENABLE)
            }, 1)
        }
        demo = button("Use bundled WAV sample") { loadDemo() }
        start = button("Export MP3") { export() }
        cancel = button("Cancel export") {
            if (job?.cancel() == true) status.text = "Cancelling…"
        }
        play = button("Play MP3") { exported?.let { play(it) } }
        save = button("Save a copy…") {
            startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                type = "audio/mpeg"; addCategory(Intent.CATEGORY_OPENABLE); putExtra(Intent.EXTRA_TITLE, "export.mp3")
            }, 2)
        }
        setContentView(ScrollView(this).apply { addView(column) })
        refresh(false)
    }

    private fun refresh(busy: Boolean) {
        pick.isEnabled = !busy; demo.isEnabled = !busy; bitrate.isEnabled = !busy
        start.isEnabled = !busy && input != null; cancel.isEnabled = busy
        play.isEnabled = !busy && exported != null; save.isEnabled = !busy && exported != null
    }

    private fun loadDemo() {
        refresh(true); cancel.isEnabled = false
        status.text = "Loading bundled WAV…"
        worker.execute {
            try {
                val file = File(cacheDir, "bundled-demo.wav")
                assets.open("demo.wav").use { source -> file.outputStream().use { source.copyTo(it) } }
                ui.execute {
                    input = Uri.fromFile(file)
                    status.text = "Bundled stereo WAV loaded. Choose a bitrate and export."
                    refresh(false)
                }
            } catch (failure: Exception) {
                ui.execute { status.text = "Cannot load the bundled WAV: ${failure.message}"; refresh(false) }
            }
        }
    }

    @Deprecated("Kept independent of optional UI libraries")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        if (requestCode == 1) {
            input = uri
            status.text = "WAV selected. Choose a bitrate and export."
            refresh(false)
        } else if (requestCode == 2) saveCopy(uri)
    }

    private fun export() {
        val selected = input ?: return
        player?.release(); player = null
        val outputDirectory = File(filesDir, "exports").apply { mkdirs() }
        val destination = File(outputDirectory, "${UUID.randomUUID()}.mp3")
        val source = PcmSources.wav(InputStreamFactory {
            contentResolver.openInputStream(selected) ?: error("The document provider did not open the WAV")
        })
        refresh(true)
        progress.progress = 0; progress.isIndeterminate = true
        status.text = "Opening WAV…"
        job = Mp3Export.start(source, destination, worker,
            Mp3ExportOptions(bitrateKbps = intArrayOf(128, 192, 256, 320)[bitrate.selectedItemPosition]), ui,
            object : Mp3ExportObserver() {
                override fun onProgress(progress: Mp3ExportProgress) {
                    val fraction = progress.inputFraction
                    val bar = this@ExportActivity.progress
                    bar.isIndeterminate = fraction == null || progress.phase != Mp3ExportPhase.ENCODING
                    if (fraction != null) bar.progress = (fraction * 1000).toInt()
                    status.text = when (progress.phase) {
                        Mp3ExportPhase.ENCODING -> "Encoding: ${progress.inputFrames} / ${progress.totalFrames ?: "unknown"} PCM frames"
                        Mp3ExportPhase.FINALIZING -> "Finalizing MP3…"
                        Mp3ExportPhase.COMMITTING -> "Saving the completed export…"
                    }
                }
                override fun onSuccess(result: Mp3ExportResult) {
                    exported = result.output
                    progress.isIndeterminate = false; progress.progress = 1000
                    status.text = "Export complete: ${result.statistics.inputFrames} frames, ${result.statistics.outputBytes} bytes, ${result.statistics.bitrateKbps} kbit/s.\n${result.output.name}"
                    refresh(false)
                }
                override fun onFailure(failure: Throwable) {
                    progress.isIndeterminate = false; progress.progress = 0
                    status.text = if (failure is dev.unicornwhodev.mp3codec.Mp3CancelledException) "Export cancelled. No incomplete MP3 was published."
                        else "Export failed: ${failure.message}"
                    refresh(false)
                }
            })
    }

    private fun play(file: File) {
        player?.release()
        player = MediaPlayer().apply {
            setDataSource(file.absolutePath)
            setOnPreparedListener { it.start(); status.append("\nPlaying the exported MP3.") }
            setOnCompletionListener { status.append("\nPlayback completed.") }
            setOnErrorListener { _, what, extra -> status.text = "Playback failed ($what/$extra)"; true }
            prepareAsync()
        }
    }

    /** Copy only a completed MP3. SAF providers do not offer a universal atomic-commit guarantee. */
    private fun saveCopy(uri: Uri) {
        val source = exported ?: return
        refresh(true); cancel.isEnabled = false; progress.isIndeterminate = true
        status.text = "Copying the completed MP3…"
        worker.execute {
            try {
                source.inputStream().use { input ->
                    (contentResolver.openOutputStream(uri, "w") ?: error("Cannot open destination")).use { output -> input.copyTo(output) }
                }
                ui.execute { status.text = "MP3 copy saved."; progress.isIndeterminate = false; refresh(false) }
            } catch (failure: Exception) {
                val deleted = try { DocumentsContract.deleteDocument(contentResolver, uri) } catch (_: Exception) { false }
                ui.execute {
                    status.text = "Copy failed: ${failure.message}" + if (deleted) "\nThe incomplete copy was removed." else "\nThe provider could not confirm cleanup; check the selected destination."
                    progress.isIndeterminate = false; refresh(false)
                }
            }
        }
    }

    override fun onDestroy() {
        job?.cancel()
        worker.shutdown() // Accepted work must still close its streams and clean temporary output.
        player?.release(); player = null
        super.onDestroy()
    }
}
