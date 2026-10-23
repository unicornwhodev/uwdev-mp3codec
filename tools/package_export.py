#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package the stable export SDK and the unchanged qualified core locally."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.3.0'
MODULE = 'io/github/unicornwhodev/uwdev-mp3codec-export'
CORE_MODULE = 'io/github/unicornwhodev/uwdev-mp3codec'
CORE_SHA = 'dc78b3b583abc95542f3d37487b2749670f75d58edbc26d00af5c342d2f574e4'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-demo', action='store_true', help='Include the built standalone demo APK and write the complete SDK ZIP')
    args = parser.parse_args()
    summary = json.loads((ROOT/'build/export-validation/summary.json').read_text())
    assert summary['status'] == 'PASS', 'Run complete local Android validation before packaging'
    assert summary['export_version'] == VERSION and summary['core_version'] == '0.2.0'
    core = ROOT/'maven'/CORE_MODULE/'0.2.0/uwdev-mp3codec-0.2.0.aar'
    assert sha(core) == CORE_SHA
    stage = ROOT/'encoder-export/build/staging-repository'
    version_dir = stage/MODULE/VERSION
    assert sha(version_dir/f'uwdev-mp3codec-export-{VERSION}.aar') == sha(ROOT/'encoder-export/build/outputs/aar/encoder-export-release.aar')
    with zipfile.ZipFile(version_dir/f'uwdev-mp3codec-export-{VERSION}-sources.jar') as sources:
        for name in ('LICENSE', 'NOTICE.md'):
            assert sources.read('META-INF/uwdev-mp3codec-export/'+name) == (ROOT/name).read_bytes()
    # Publish only this stable version. Never carry local SNAPSHOT metadata forward.
    destination = ROOT/'maven'/MODULE/VERSION
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(version_dir.iterdir()):
        if path.is_file():
            target = destination/path.name
            assert not target.exists() or target.read_bytes() == path.read_bytes(), 'Refuse to replace an existing stable artifact'
            shutil.copyfile(path, target)
    metadata = f'''<?xml version="1.0" encoding="UTF-8"?>
<metadata><groupId>io.github.unicornwhodev</groupId><artifactId>uwdev-mp3codec-export</artifactId><versioning><latest>{VERSION}</latest><release>{VERSION}</release><versions><version>{VERSION}</version></versions></versioning></metadata>
'''.encode('utf-8')
    metadata_path = ROOT/'maven'/MODULE/'maven-metadata.xml'
    metadata_path.write_bytes(metadata)
    for algorithm in ('md5','sha1','sha256','sha512'):
        metadata_path.with_name(metadata_path.name+'.'+algorithm).write_text(hashlib.new(algorithm, metadata).hexdigest(), encoding='ascii')
    output = ROOT/f'build/release-{VERSION}'
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output/f'uwdev-mp3codec-{VERSION}-maven.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT/'maven').rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT/'maven').as_posix())
    shutil.copyfile(ROOT/'encoder-export/build/outputs/aar/encoder-export-release.aar', output/f'uwdev-mp3codec-export-{VERSION}.aar')
    shutil.copyfile(core, output/core.name)
    shutil.copyfile(version_dir/f'uwdev-mp3codec-export-{VERSION}-sources.jar', output/f'uwdev-mp3codec-export-{VERSION}-sources.jar')
    for name in ('LICENSE', 'NOTICE.md'):
        shutil.copyfile(ROOT/name, output/name)
    shutil.copyfile(ROOT/'docs/EXPORT.md', output/'EXPORT.md')
    shutil.copyfile(ROOT/'docs/EXPORT_VALIDATION.md', output/'EXPORT_VALIDATION.md')
    independent = ROOT/'build/export-validation/java-consumer-result.json'
    if independent.exists():
        summary['checks']['independent_java_maven_consumer'] = json.loads(independent.read_text())
        assert summary['checks']['independent_java_maven_consumer']['status'] == 'PASS'
    if args.with_demo:
        smoke = json.loads((ROOT/'build/export-validation/sdk-demo-smoke.json').read_text())
        assert smoke['status'] == 'PASS'
        summary['checks']['standalone_sdk_demo'] = smoke
    (output/'VALIDATION.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    sdk = output/'sdk'
    sdk_files = set()
    def copy(source, relative):
        target = sdk/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        sdk_files.add(target)
    def write(relative, contents):
        target = sdk/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding='utf-8')
        sdk_files.add(target)
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            write_path = sdk/'maven'/name
            write_path.parent.mkdir(parents=True, exist_ok=True)
            write_path.write_bytes(archive.read(name))
            sdk_files.add(write_path)
    for name in ('LICENSE','NOTICE.md','VALIDATION.json'):
        copy(output/name, name)
    for path in sorted((ROOT/'docs').glob('*.md')):
        copy(path, 'docs/'+path.name)
    for path in sorted((ROOT/'qualification').glob('*.json')):
        copy(path, 'qualification/'+path.name)
    copy(ROOT/'tools/generate_demo_wav.py', 'tools/generate_demo_wav.py')
    copy(ROOT/'tools/validate_demo.py', 'tools/validate_demo.py')
    for path in sorted((ROOT/'third-party-notices').iterdir()):
        if path.is_file(): copy(path, 'third-party-notices/'+path.name)
    copy(output/f'uwdev-mp3codec-export-{VERSION}.aar', 'aar/'+f'uwdev-mp3codec-export-{VERSION}.aar')
    copy(core, 'aar/'+core.name)
    for name in ('gradlew','gradlew.bat','gradle/wrapper/gradle-wrapper.jar','gradle/wrapper/gradle-wrapper.properties'):
        copy(ROOT/name, 'example/android/'+name)
    copy(ROOT/'sample-app/src/main/kotlin/dev/unicornwhodev/mp3codec/sample/ExportActivity.kt',
         'example/android/app/src/main/kotlin/dev/unicornwhodev/mp3codec/sample/ExportActivity.kt')
    for path in (ROOT/'sample-app/src/main/assets').iterdir():
        if path.is_file():
            copy(path, 'example/android/app/src/main/assets/'+path.name)
            copy(path, 'demo/'+path.name)
    write('example/android/settings.gradle.kts', '''pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { maven { url = uri(rootDir.resolve("../../maven")) }; google(); mavenCentral() } }
rootProject.name = "uwdev-mp3codec-demo"
include(":app")
''')
    write('example/android/build.gradle.kts', '''plugins {
    id("com.android.application") version "8.11.1" apply false
    id("org.jetbrains.kotlin.android") version "2.2.21" apply false
}
''')
    write('example/android/gradle.properties', 'org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8\nandroid.useAndroidX=true\n')
    write('example/android/app/build.gradle.kts', '''plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "dev.unicornwhodev.mp3codec.sample"
    compileSdk = 36
    defaultConfig { applicationId = "dev.unicornwhodev.mp3codec.demo"; minSdk = 26; targetSdk = 36; versionCode = 3; versionName = "0.3.0" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    buildTypes { getByName("release") { isMinifyEnabled = true; proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt")); signingConfig = signingConfigs.getByName("debug") } }
}
kotlin { jvmToolchain(17) }
dependencies { implementation("io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0") }
''')
    write('example/android/app/src/main/AndroidManifest.xml', '''<manifest xmlns:android="http://schemas.android.com/apk/res/android">
<application android:label="uwdev MP3 Export Demo" android:theme="@android:style/Theme.Material.Light.NoActionBar" android:allowBackup="false">
<activity android:name=".ExportActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>
</application></manifest>
''')
    write('example/kotlin/EncodeWav.kt', '''// SPDX-License-Identifier: MIT
import dev.unicornwhodev.mp3codec.export.*
import java.io.File

// Blocking example: call on a worker thread. See docs/EXPORT.md for async jobs.
fun encodeWav(input: File, output: File): Mp3ExportResult =
    Mp3Export.fromWav(input, output, Mp3Preset.HIGH_256)
''')
    write('example/java/EncodePcm.java', '''// SPDX-License-Identifier: MIT
import dev.unicornwhodev.mp3codec.export.*;
import java.io.File;

public final class EncodePcm {
    // Blocking example: call on a worker thread. The source contains raw PCM, not a WAV header.
    public static Mp3ExportResult encode(File input, File output) {
        PcmSource source = PcmSources.pcm(input, new PcmFormat(48000, 2));
        return Mp3Export.encode(source, output, new Mp3ExportOptions(256));
    }
}
''')
    write('example/README.md', '''# Encoding examples

`android` is a complete, independent Android Studio/Gradle application. It resolves
the facade 0.3.0 and qualified core 0.2.0 from `../../maven` relative to its root.
Use JDK 17 and Android SDK 36, then run `gradlew.bat :app:assembleRelease` on Windows
or `sh ./gradlew :app:assembleRelease` on Linux/macOS. No NDK or CMake is required.

`kotlin/EncodeWav.kt` and `java/EncodePcm.java` show minimal blocking calls for an
existing Android application. Run them on a worker thread. See `docs/EXPORT.md`
at the SDK/package root for background jobs, progress, cancellation and safe output.

The demo APK is in `demo` at the SDK/package root. It supports WAV selection,
a bundled original MIT sample, all four bitrates, playback and saving a copy.
Keep the root LICENSE, NOTICE.md and applicable third-party notices when copying.
''')
    write('README.md', '''# uwdev-mp3codec SDK 0.3.0

This package includes the qualified 0.2.0 Android codec and its optional export facade.
Documentation and examples are in English. No CI or GitHub workflow is included.

## Try the demo immediately

Install `demo/uwdev-mp3codec-demo.apk` on Android 8/API 26 or later.
Tap **Use bundled WAV sample**, choose a bitrate, then **Export MP3**.
Tap **Play MP3** or **Save a copy** after success. You can also choose your own PCM16 WAV.
The original two-second sample and its MIT provenance/hash are included in `demo`.
The demo APK is a non-debuggable R8 Release signed locally with an Android debug key.
No signing key is included; the APK is an integration demonstration.

## Add the dependency to an application

Extract this SDK and add its `maven` directory as a local Gradle Maven repository.
Use `implementation("io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0")`.
The qualified core and Kotlin runtime are resolved transitively. For manual installation,
include both AARs from `aar` and Kotlin stdlib 2.2.21. No NDK/CMake is needed by consumers.
See `docs/EXPORT.md` for threading, progress, cancellation, stream ownership and output safety.
See `example/kotlin/EncodeWav.kt` and `example/java/EncodePcm.java` for minimal encoding calls.

## Build and adapt the complete demo

Open `example/android` in Android Studio, or enter that folder and run
`sh ./gradlew :app:assembleRelease` (`gradlew.bat` on Windows), with JDK 17 and Android SDK 36.
The example consumes only the packaged Maven artifacts and can be copied independently.
It requires access to Google/Maven Central for Android build tools and Kotlin on first build;
cached builds can run with `--offline`. The MP3 encoder itself works offline.

## License and verification

MIT permits commercial use under its notice-retention terms. Preserve LICENSE, NOTICE.md
and applicable third-party notices. The core AAR embeds its original notices.
Read `docs/EXPORT_VALIDATION.md` and `VALIDATION.json`; verify `SHA256SUMS` before use.
The export facade is version 0.3.0; the qualified native core remains version 0.2.0.
''')
    if args.with_demo:
        demo_apk = sdk/'example/android/app/build/outputs/apk/release/app-release.apk'
        assert demo_apk.is_file(), 'Build the standalone SDK demo first; see docs/EXPORT.md'
        assert sha(demo_apk) == summary['checks']['standalone_sdk_demo']['apk_sha256'], 'Demo APK differs from the tested binary'
        with zipfile.ZipFile(core) as frozen, zipfile.ZipFile(demo_apk) as demo:
            for abi in ('arm64-v8a','armeabi-v7a','x86_64'):
                assert frozen.read(f'jni/{abi}/libuwdev_mp3codec.so') == demo.read(f'lib/{abi}/libuwdev_mp3codec.so')
        copy(demo_apk, 'demo/uwdev-mp3codec-demo.apk')
        sdk_sums = ''.join(sha(path)+'  '+path.relative_to(sdk).as_posix()+'\n' for path in sorted(sdk_files))
        write('SHA256SUMS', sdk_sums)
        with zipfile.ZipFile(output/f'uwdev-mp3codec-{VERSION}-sdk.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(sdk_files): archive.write(path, path.relative_to(sdk).as_posix())
    files = sorted(p for p in output.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
    (output/'SHA256SUMS').write_text(''.join(sha(path)+'  '+path.name+'\n' for path in files), encoding='ascii')
    print(f'Validated release assets: build/release-{VERSION}')
    print('Maven ZIP includes both the facade and the frozen qualified core.')
    print('Complete SDK ZIP ready.' if args.with_demo else 'SDK staged; build example/android, then rerun with --with-demo to include the APK.')

if __name__ == '__main__':
    main()
