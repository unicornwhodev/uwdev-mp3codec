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
        versionCode = 3
        versionName = "0.3.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        testProguardFiles("test-rules.pro")
    }
    testBuildType = "release"
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
            if (localDeviceQa) {
                signingConfig = signingConfigs.getByName("debug")
                proguardFiles("qa-test-target-rules.pro")
            }
        }
    }
}

kotlin { jvmToolchain(17) }
dependencies {
    implementation(project(":encoder-export"))
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    // Compile-only annotations referenced by AndroidX Test; needed by the minified test APK.
    androidTestImplementation("com.google.errorprone:error_prone_annotations:2.36.0")
}
