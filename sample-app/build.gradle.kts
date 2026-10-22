// SPDX-License-Identifier: MIT
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val localDeviceQa = providers.gradleProperty("uwdevLocalDeviceQa").orNull == "true"

android {
    namespace = "dev.unicornwhodev.mp3codec.sample"
    compileSdk = 36
    ndkVersion = "27.2.12479018"
    defaultConfig {
        applicationId = "dev.unicornwhodev.mp3codec.sample"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = providers.gradleProperty("uwdevVersion").get()
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
            if (localDeviceQa) signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin { jvmToolchain(17) }
dependencies { implementation(project(":encoder-android")) }
