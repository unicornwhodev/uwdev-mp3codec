// SPDX-License-Identifier: MIT
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven {
            url = uri(rootDir.resolve("maven"))
            content { includeModule("io.github.unicornwhodev", "uwdev-mp3codec") }
        }
        google()
        mavenCentral()
    }
}
rootProject.name = "uwdev-mp3codec"
include(":encoder-android", ":encoder-export", ":sample-app")
