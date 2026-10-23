// SPDX-License-Identifier: MIT
plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("maven-publish")
}

group = "io.github.unicornwhodev"
version = "0.3.0"

android {
    namespace = "dev.unicornwhodev.mp3codec.export"
    compileSdk = 36
    defaultConfig {
        minSdk = 26
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    publishing { singleVariant("release") { withSourcesJar() } }
    testOptions { unitTests.isReturnDefaultValues = true }
    sourceSets.getByName("main").resources.srcDir("src/main/resources")
}

kotlin { jvmToolchain(17) }
dependencies {
    // Resolve the frozen qualified binary, never the native source project.
    api("io.github.unicornwhodev:uwdev-mp3codec:0.2.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}

val exportNotices by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/export-notices/META-INF/uwdev-mp3codec-export"))
    from(rootProject.file("LICENSE"))
    from(rootProject.file("NOTICE.md"))
}
android.sourceSets.getByName("main").resources.srcDir(layout.buildDirectory.dir("generated/export-notices"))
tasks.named("preBuild").configure { dependsOn(exportNotices) }

publishing {
    publications {
        register<MavenPublication>("release") {
            artifactId = "uwdev-mp3codec-export"
            afterEvaluate { from(components["release"]) }
            pom {
                name.set("uwdev-mp3codec export helpers")
                description.set("PCM/WAV export facade around the frozen qualified Android encoder")
                url.set("https://github.com/unicornwhodev/uwdev-mp3codec")
                licenses { license { name.set("MIT License"); url.set("https://opensource.org/license/mit/") } }
                developers { developer { id.set("unicornwhodev"); name.set("Unicorn Who Dev") } }
                scm { url.set("https://github.com/unicornwhodev/uwdev-mp3codec") }
            }
        }
    }
    repositories { maven { name = "staging"; url = uri(layout.buildDirectory.dir("staging-repository")) } }
}

// Keep the permission and attribution text with the standalone sources artifact.
afterEvaluate {
    tasks.named<org.gradle.api.tasks.bundling.Zip>("sourceReleaseJar") {
        from(rootProject.file("LICENSE")) { into("META-INF/uwdev-mp3codec-export") }
        from(rootProject.file("NOTICE.md")) { into("META-INF/uwdev-mp3codec-export") }
    }
}
