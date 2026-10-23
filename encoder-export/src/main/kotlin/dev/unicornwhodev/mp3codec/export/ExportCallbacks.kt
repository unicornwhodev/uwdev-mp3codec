// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec.export

import java.util.concurrent.Executor

/** At most one queued progress value and one terminal notification, even if the UI is stalled. */
internal class ExportCallbacks(
    private val executor: Executor,
    private val observer: Mp3ExportObserver?,
    private val failed: (Throwable) -> Unit = {},
) {
    private val lock = Any()
    private var progress: Mp3ExportProgress? = null
    private var terminal: (() -> Unit)? = null
    private var scheduled = false
    private var closed = false

    fun progress(value: Mp3ExportProgress) {
        if (observer == null) return
        synchronized(lock) { if (closed || terminal != null) return; progress = value }
        schedule()
    }
    fun success(value: Mp3ExportResult) = terminate { observer?.onSuccess(value) }
    fun failure(value: Throwable) = terminate { observer?.onFailure(value) }
    private fun terminate(action: () -> Unit) {
        if (observer == null) return
        synchronized(lock) { if (closed || terminal != null) return; terminal = action }
        schedule()
    }
    private fun schedule() {
        synchronized(lock) { if (scheduled || closed) return; scheduled = true }
        try { executor.execute { drain() } }
        catch (failure: Throwable) {
            synchronized(lock) { progress = null; terminal = null; scheduled = false; closed = true }
            failed(failure)
        }
    }
    private fun drain() {
        while (true) {
            val action = synchronized(lock) {
                val latest = progress
                if (latest != null) {
                    progress = null
                    { observer?.onProgress(latest); Unit }
                } else {
                    val final = terminal
                    if (final != null) { terminal = null; closed = true }
                    else scheduled = false
                    final
                }
            } ?: return
            try { action() } catch (failure: Throwable) { failed(failure) }
            if (synchronized(lock) { closed }) return
        }
    }
}
