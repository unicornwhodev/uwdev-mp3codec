pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { maven { url = uri(rootDir.resolve("../../maven")) }; google(); mavenCentral() } }
rootProject.name = "uwdev-mp3codec-demo"
include(":app")
