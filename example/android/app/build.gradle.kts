plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "dev.unicornwhodev.mp3codec.sample"
    compileSdk = 36
    defaultConfig { applicationId = "dev.unicornwhodev.mp3codec.demo"; minSdk = 26; targetSdk = 36; versionCode = 3; versionName = "0.3.0" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    buildTypes { getByName("release") { isMinifyEnabled = true; proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt")); signingConfig = signingConfigs.getByName("debug") } }
}
kotlin { jvmToolchain(17) }
dependencies { implementation("io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0") }
