# Migrating to uwdev-mp3codec 0.2.0

Replace the former `dev.unicornwhodev.mp3encoder` imports with
`dev.unicornwhodev.mp3codec`, and use the Maven coordinate
`io.github.unicornwhodev:uwdev-mp3codec:0.2.0`.

The public encoder, configuration, statistics and exception signatures remain
available. `Mp3EncodingStats` keeps its six-argument constructor and adds readable
peak-protection diagnostics. Rebuild consumers after updating imports.

The native library is `libuwdev_mp3codec.so`; the internal C++ namespace is
`uwdev::mp3codec`. The public API remains PCM-to-MP3. WAV parsing and WAV witness
generation belong to applications and test tools.

The 0.2.0 stable AAR is byte-identical to the final qualified 0.2.0 development
artifact. No other codec implementation is bundled or used as a fallback.
