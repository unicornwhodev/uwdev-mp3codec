# Kotlin JVM runtime and annotations provenance

The Maven publication declares `org.jetbrains.kotlin:kotlin-stdlib:2.2.21`.
Its POM declares Apache-2.0 and a dependency on
`org.jetbrains:annotations:13.0`, whose POM also declares Apache-2.0.
These JARs are resolved by the consuming build; they are not merged into
the library AAR. The sample APK packages the Kotlin JVM runtime.

Primary artifact metadata:

- <https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/2.2.21/kotlin-stdlib-2.2.21.pom>
  SHA-256: `cf31f923196c63aedecd0a57c24269bd3702a4e47c0bf0bd64b5ada5de522272`.
- <https://repo.maven.apache.org/maven2/org/jetbrains/annotations/13.0/annotations-13.0.pom>
  SHA-256: `965aeb2bedff369819bdde1bf7a0b3b89b8247dd69c88b86375d76163bb8c397`.
- Resolved Kotlin stdlib JAR SHA-256:
  `6558a3d233da56a20934b32159f9db5f86ed5816ef098f78a2c223dc6abb79dd`.
- Resolved JetBrains annotations JAR SHA-256:
  `ace2a10dc8e2d5fd34925ecac03e4988b2c0f851650c94b8cef49ba1bd111478`.

Kotlin's `v2.2.21` tag resolves to commit
`2146684dcba708e5a304758b41a9e4ec9c7eff71`. Its
[license inventory](https://github.com/JetBrains/kotlin/blob/2146684dcba708e5a304758b41a9e4ec9c7eff71/license/README.md)
identifies additional portions of the JVM/common standard library. The
relevant unmodified upstream texts are retained here:

| Local notice | Upstream path below `license/` | Scope and attribution recorded upstream |
|---|---|---|
| `Kotlin-2.2.21-LICENSE.txt` | `LICENSE.txt` | Apache-2.0 for JetBrains Kotlin code |
| `Kotlin-2.2.21-COPYRIGHT.txt` | `COPYRIGHT.txt` | Copyright 2010–2024 JetBrains s.r.o. and Kotlin Programming Language contributors |
| `Kotlin-GWT-Apache-2.0.txt` | `third_party/gwt_license.txt` | Apache-2.0; collections derived from GWT, copyright 2007–2008 Google Inc. |
| `Kotlin-Guava-Apache-2.0.txt` | `third_party/guava_license.txt` | Apache-2.0; JVM unsigned arithmetic derived from Guava, copyright 2011 The Guava Authors |
| `Kotlin-ThreeTenBP-BSD-3-Clause.txt` | `third_party/threetenbp_license.txt` | BSD-3-Clause; common time code, copyright 2007–present Stephen Colebourne and Michael Nascimento Santos |
| `Kotlin-Boost-BSL-1.0.txt` | `third_party/boost_LICENSE.txt` | BSL-1.0; JVM math derived from Boost special functions, copyright Eric Ford and Hubert Holin 2001 |

JetBrains annotations 13.0 identifies the JetBrains Team as its developer in
the POM. Its Apache-2.0 terms are reproduced by the Apache license text above;
the artifact is not claimed to be original MIT project code. No copyright
year absent from that artifact metadata is invented here.

The Kotlin compiler, JavaScript/Native/Wasm backends and upstream test data
have a wider dependency inventory. Their implementation is not distributed
in this project's source or AAR. This notice records the JVM runtime scope;
it is not a claim that every file in the upstream Kotlin repository has one
license. File hashes and the audited distribution scope are recorded by
`tools/audit_source_licenses.py` and `docs/LICENSE_AUDIT.md`.
