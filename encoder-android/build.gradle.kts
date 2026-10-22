// SPDX-License-Identifier: MIT
plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("maven-publish")
}

group = "io.github.unicornwhodev"
version = providers.gradleProperty("uwdevVersion").get()

val licenseResources = layout.buildDirectory.dir("generated/license-resources")
val syncLicenseNotices by tasks.registering(Sync::class) {
    into(licenseResources.map { it.dir("META-INF/uwdev-mp3codec") })
    from(rootProject.file("LICENSE"))
    from(rootProject.file("NOTICE.md"))
    from(rootProject.file("third-party-notices")) { into("third-party-notices") }
}

android {
    namespace = "dev.unicornwhodev.mp3codec"
    compileSdk = 36
    ndkVersion = "27.2.12479018"
    defaultConfig {
        minSdk = 26
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
        ndk {
            abiFilters += setOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }
        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_STL=c++_static", "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON")
                cppFlags += listOf("-std=c++17")
            }
        }
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    publishing {
        singleVariant("release") {
            withSourcesJar()
        }
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
    sourceSets.getByName("main").resources.srcDir(licenseResources)
}

tasks.named("preBuild").configure { dependsOn(syncLicenseNotices) }
tasks.withType<Jar>().configureEach {
    if (name == "sourceReleaseJar") {
        from("src/main/cpp") { into("native") }
        from(rootProject.file("LICENSE")) { into("META-INF/uwdev-mp3codec") }
        from(rootProject.file("NOTICE.md")) { into("META-INF/uwdev-mp3codec") }
        from(rootProject.file("third-party-notices")) { into("META-INF/uwdev-mp3codec/third-party-notices") }
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}

publishing {
    publications {
        register<MavenPublication>("release") {
            groupId = "io.github.unicornwhodev"
            artifactId = "uwdev-mp3codec"
            version = project.version.toString()
            afterEvaluate { from(components["release"]) }
            pom {
                name.set("uwdev-mp3codec for Android")
                description.set("Independent native MPEG-1 Layer III PCM encoder for Android")
                url.set("https://github.com/unicornwhodev/uwdev-mp3codec")
                licenses {
                    license {
                        name.set("MIT License")
                        url.set("https://opensource.org/license/mit/")
                    }
                }
                developers {
                    developer {
                        id.set("unicornwhodev")
                        name.set("Unicorn Who Dev")
                    }
                }
                scm {
                    connection.set("scm:git:https://github.com/unicornwhodev/uwdev-mp3codec.git")
                    url.set("https://github.com/unicornwhodev/uwdev-mp3codec")
                }
            }
        }
    }
    repositories {
        maven {
            name = "staging"
            url = uri(layout.buildDirectory.dir("staging-repository"))
        }
    }
}

