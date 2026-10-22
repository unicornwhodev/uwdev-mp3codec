# Security and privacy

The Android encoder has no runtime network permission or network service dependency.
Use supported configurations, complete PCM frames, worker-thread encoding and the
documented output-commit pattern. An output error or failed `finish()` makes an
export unusable; the caller must discard its temporary destination.

The npm package has no runtime dependencies or lifecycle install scripts. Its
helpers locate bundled Android artifacts and verify their SHA-256 manifest.
Release assets also include a SHA-256 manifest.

Do not put tokens, signing keys, device dumps or application recordings in public
issues. Report reproducible security problems through the repository's private
security reporting feature where available. Public source is exported without
private development history, workstation paths or device identifiers.
