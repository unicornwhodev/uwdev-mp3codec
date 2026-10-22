#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inventory the reviewed source, notices, and Android distribution artifacts.

Offline, standard-library-only audit. This verifies the explicit provenance
policy in docs/LICENSE_AUDIT.md; it cannot establish legal title or detect all
unattributed copying. No production file or archive is modified.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile


CODEC = "encoder-android/src/main/cpp/codec/"
NOTICE_PREFIX = "META-INF/uwdev-mp3codec/"
KOTLIN_COMMIT = "2146684dcba708e5a304758b41a9e4ec9c7eff71"
MINIMP3_COMMIT = "ea99364f61c14656440e8d77e9c233ccf3124633"
PL_MPEG_COMMIT = "c871f2be022ece7ef4f64230b4fb8e1fb9eb6023"
EXCLUDED_DIRECTORIES = {
    ".git", ".gradle", ".kotlin", ".cxx", ".idea", "build", "__pycache__", "node_modules",
}
PRODUCTION_ROOTS = ("encoder-android/src/main/", "sample-app/src/main/")
KNOWN_SOURCE_ROOTS = {
    "docs", "encoder-android", "sample-app", "validation-app", "native-tests",
    "scripts", "tools", "gradle", "third-party-notices", "lib", "bin", "test", "qualification",
}
KNOWN_ROOT_FILES = {
    ".gitattributes", ".gitignore", "LICENSE", "NOTICE.md", "README.md", "CHANGELOG.md", "SECURITY.md", "package.json", "package-lock.json", "INTEGRITY.json",
    "build.gradle.kts", "settings.gradle.kts", "gradle.properties",
    "gradlew", "gradlew.bat",
}
PINNED_SHA256 = {
    "gradlew": "734b3879d3501dce471cf0522d3bcbafe76873d9fc5129345b67fb43bd15e933",
    "gradlew.bat": "57931b17dd228e5c24dac90e815d0bf82477e831a4618dfab4136f5446b42a9f",
    "gradle/wrapper/gradle-wrapper.jar": "81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f",
    CODEC + "huffman_tables.hpp": "e367d50d7c529b4f4eab39764df3a4a6cacf1d852d3a3afe4249ec986af69c2f",
    CODEC + "synthesis_window.hpp": "f047f7b0599346608c1fdce06d9d02ea67add144f08e34ab03cbcfe5e0695394",
    "third-party-notices/minimp3-CC0.txt": "6a1ee543e5282cd9061881edf462e6fdab181f328da71fc2c9a6950a80e94d01",
    "third-party-notices/pl_mpeg-MIT.txt": "b413c5bb523e7ef870a90b5617912ea211514697fa0428242fc4f2c6cc426d28",
    "third-party-notices/Gradle-LICENSE.txt": "9536d88ea948603d18e232a13f5958d67807cd80828036b082bff171d2cf0703",
    "third-party-notices/Gradle-NOTICE.txt": "c2de5fd9adc7ccc4e1382a0e1f38ec6e14f8ca6e28d3c20289fe80353b019aa1",
    "third-party-notices/Android-NDK-r27c-LLVM-NOTICE.txt": "f96f763beb66a7ba7a667647fc64c0226ace875e590c831fdd9579ec1c1d91e1",
    "third-party-notices/Kotlin-2.2.21-LICENSE.txt": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "third-party-notices/Kotlin-2.2.21-COPYRIGHT.txt": "8f1a1700adb5490604c6094fb137bf73f6c28d3ee554b58f3ff8ef975a79672d",
    "third-party-notices/Kotlin-GWT-Apache-2.0.txt": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "third-party-notices/Kotlin-Guava-Apache-2.0.txt": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "third-party-notices/Kotlin-ThreeTenBP-BSD-3-Clause.txt": "d1bc53b493a3ab387b42717ed5c4b1976a5048996f81154278100bff86d39331",
    "third-party-notices/Kotlin-Boost-BSL-1.0.txt": "8d8291caf1cee26d23acf3eb67c9f9a2d58f1c681b16a4fbe8cbfb9e3c0b5a9b",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classification(kind: str, licenses: list[str], provenance: str) -> dict:
    return {"license_class": kind, "license_components": licenses, "provenance": provenance}


def classify_source(path: str) -> dict:
    if path in {"gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.jar"}:
        return classification("third_party_build_tool", ["Apache-2.0"], "Unmodified Gradle 8.13 generated wrapper; retained Gradle license and notice.")
    if path == CODEC + "synthesis_window.hpp":
        return classification("third_party_numeric_data_with_original_arrangement", ["MIT"], "512 numeric values only from pl_mpeg at " + PL_MPEG_COMMIT + "; docs/DSP_SOURCES.md.")
    if path in {CODEC + name for name in ("dsp.cpp", "mpeg.cpp", "huffman_tables.hpp")}:
        return classification("original_mit_with_cc0_numeric_data", ["MIT", "CC0-1.0"], "Original implementation/arrangement; minimp3 numeric tables at " + MINIMP3_COMMIT + "; docs/MPEG_SOURCES.md and docs/DSP_SOURCES.md.")
    if path.startswith("third-party-notices/") and path.endswith(".txt"):
        name = PurePosixPath(path).name
        if name == "minimp3-CC0.txt":
            licenses = ["CC0-1.0"]
        elif name == "pl_mpeg-MIT.txt":
            licenses = ["MIT"]
        elif name == "Android-NDK-r27c-LLVM-NOTICE.txt":
            licenses = ["Apache-2.0 WITH LLVM-exception", "LicenseRef-NDK-r27c-aggregate-notices"]
        elif name in {"Gradle-LICENSE.txt", "Gradle-NOTICE.txt"}:
            licenses = ["Apache-2.0", "LicenseRef-Gradle-8.13-aggregate-notices"]
        elif name == "Kotlin-ThreeTenBP-BSD-3-Clause.txt":
            licenses = ["BSD-3-Clause"]
        elif name == "Kotlin-Boost-BSL-1.0.txt":
            licenses = ["BSL-1.0"]
        elif name.startswith(("Kotlin-", "Gradle-")):
            licenses = ["Apache-2.0"]
        else:
            return classification("unreviewed_notice", [], "New third-party notice requires explicit classification.")
        return classification("retained_third_party_notice", licenses, "Notice text is retained under its upstream terms, not relicensed as original project code.")
    if path.startswith("docs/evidence/"):
        return classification("generated_project_evidence", ["MIT"], "Output of the project's original test/review procedures; external tool implementation is not incorporated.")
    if path in KNOWN_ROOT_FILES or PurePosixPath(path).parts[0] in KNOWN_SOURCE_ROOTS:
        if Path(path).suffix in {".jar", ".so", ".a", ".aar", ".apk", ".zip", ".wasm", ".exe", ".dll"}:
            return classification("unreviewed_binary", [], "Unexpected vendored binary outside the reviewed Gradle wrapper.")
        return classification("original_project_mit", ["MIT"], "Project-authored source, build configuration, documentation, or tests; root LICENSE.")
    return classification("unreviewed_file", [], "Path is outside the reviewed source scope.")


def source_files(root: Path) -> tuple[list[Path], list[str]]:
    found, excluded_evidence = [], []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if name not in EXCLUDED_DIRECTORIES)
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if name == "local.properties" or name.endswith((".pyc", ".iml")):
                continue
            if relative.startswith(("docs/results/", "docs/baseline-delivery/", "artifacts/", "maven/")) or (path.suffix==".log" and "/" not in relative):
                excluded_evidence.append(relative)
            else:
                found.append(path)
    return sorted(found), sorted(excluded_evidence)


def inventory_sources(root: Path, errors: list[str]) -> tuple[list[dict], list[str]]:
    paths, excluded = source_files(root)
    rows = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append("Source symlink needs review: " + relative)
            continue
        data = path.read_bytes()
        row = {"path": relative, "bytes": len(data), "sha256": sha256(data), **classify_source(relative)}
        if row["license_class"].startswith("unreviewed"):
            errors.append("Unclassified file: " + relative)
        if path.suffix != ".jar":
            text = data.decode("utf-8", errors="replace")
            header = "\n".join(text.splitlines()[:32])
            spdx = re.search(r"(?m)^\s*(?://|#|\*|@rem|<!--)\s*SPDX-License-Identifier:[ \t]*([^\r\n]+)", header)
            if spdx:
                row["declared_spdx"] = re.sub(r"\s*(?:\*/|-->)\s*$", "", spdx.group(1)).strip()
                if row["license_class"] in {"original_project_mit", "generated_project_evidence"} and row["declared_spdx"] != "MIT":
                    errors.append("Non-MIT declaration in a project-original classification requires review: " + relative)
        rows.append(row)
    by_path = {row["path"]: row for row in rows}
    for path, expected in PINNED_SHA256.items():
        if by_path.get(path, {}).get("sha256") != expected:
            errors.append("Pinned third-party/data file missing or changed: " + path)
    return rows, excluded


def scan_production(root: Path, rows: list[dict], errors: list[str]) -> dict:
    patterns = {
        "external_encoder_or_decoder": re.compile(r"\b(?:lame|shine|ffmpeg|libavcodec|libavformat|libmp3lame|mpg123|MediaCodec|WebAssembly|wasm)\b|\b(?:lame_|shine_|avcodec_|mpg123_)", re.I),
        "copyleft_license_marker": re.compile(r"\b(?:A?GPL|LGPL)(?:[- v]?\d)?\b|GNU (?:Affero |Lesser )?General Public License", re.I),
        "network_api": re.compile(r"\b(?:java\.net|javax\.net|okhttp3?|retrofit2?|HttpURLConnection|URLConnection|WebSocket|curl_easy_\w*|getaddrinfo|socket|connect|sendto|recvfrom)\b|android\.permission\.(?:INTERNET|ACCESS_NETWORK_STATE)"),
        "runtime_url": re.compile(r"https?://(?!schemas\.android\.com/apk/res/android)[^\s\"<>]+", re.I),
    }
    scanned, findings = [], []
    for row in rows:
        name = row["path"]
        if not name.startswith(PRODUCTION_ROOTS):
            continue
        scanned.append(name)
        for line_number, line in enumerate((root / name).read_text(errors="replace").splitlines(), 1):
            for kind, pattern in patterns.items():
                if pattern.search(line):
                    findings.append({"path": name, "line": line_number, "kind": kind, "text": line.strip()})
    for finding in findings:
        errors.append(f"Production scan requires review: {finding['path']}:{finding['line']} ({finding['kind']})")
    permissions = {}
    for name in ("encoder-android/src/main/AndroidManifest.xml", "sample-app/src/main/AndroidManifest.xml"):
        tree = ET.fromstring((root / name).read_bytes())
        permissions[name] = sorted(node.attrib.get("{http://schemas.android.com/apk/res/android}name", "") for node in tree.findall("uses-permission"))
    cmake = (root / "encoder-android/src/main/cpp/CMakeLists.txt").read_text()
    gradle = (root / "encoder-android/build.gradle.kts").read_text()
    if "-DANDROID_STL=c++_static" not in gradle:
        errors.append("Reviewed static C++ runtime build setting changed.")
    forbidden_build = re.compile(r"FetchContent|ExternalProject|add_subdirectory\s*\(|IMPORTED\b")
    if forbidden_build.search(cmake):
        errors.append("Native build now has an external/subproject dependency requiring review.")
    return {
        "roots": list(PRODUCTION_ROOTS), "files_scanned": scanned, "findings": findings,
        "manifest_permissions": permissions,
        "method": "Literal source scan including comments; known format/XML namespace is excluded from URL hits. Test, documentation and notice text is outside the production scan. This is not a universal copying or behavior detector.",
        "build_network_scope": "Gradle/Maven repository resolution and publication occur on the build host. No Android network permission or matched runtime network API is accepted by this scan.",
    }


def required_notices(root: Path) -> dict[str, bytes]:
    result = {"LICENSE": (root / "LICENSE").read_bytes(), "NOTICE.md": (root / "NOTICE.md").read_bytes()}
    for path in sorted((root / "third-party-notices").rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def native_components() -> dict:
    return classification("compiled_original_with_numeric_data_and_static_runtime", ["MIT", "CC0-1.0", "Apache-2.0 WITH LLVM-exception", "LicenseRef-NDK-r27c-aggregate-notices"], "Original codec/JNI plus attributed numeric tables and statically linked NDK r27c libc++/ABI/unwinding/compiler support; retained full NDK LLVM notice.")


def inspect_elf(data: bytes, readelf: str | None, errors: list[str], name: str) -> dict:
    if not readelf:
        errors.append("readelf is required for native dependency inspection.")
        return {"inspected": False}
    with tempfile.TemporaryDirectory(prefix="uwdev-license-elf-") as directory:
        path = Path(directory) / "library.so"
        path.write_bytes(data)
        dynamic = subprocess.check_output([readelf, "-W", "-d", str(path)], text=True)
        symbols = subprocess.check_output([readelf, "-W", "--dyn-syms", str(path)], text=True)
    needed = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dynamic)
    unexpected = sorted(set(needed) - {"libc.so", "libm.so", "libdl.so", "liblog.so", "libandroid.so"})
    if unexpected:
        errors.append(name + " has unreviewed DT_NEEDED libraries: " + ", ".join(unexpected))
    imports = []
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[6] == "UND":
            imports.append(fields[7].split("@", 1)[0])
    network = sorted(name for name in imports if re.fullmatch(r"socket|connect|send|recv|sendto|recvfrom|getaddrinfo|curl_.*|SSL_.*", name))
    if network:
        errors.append(name + " has network symbol imports requiring review: " + ", ".join(network))
    signatures = sorted(set(match.group().decode("ascii") for match in re.finditer(rb"(?i)libmp3lame|lame_init|avcodec_|shine_|ffmpeg|mpg123_", data)))
    if signatures:
        errors.append(name + " has external codec signatures requiring review: " + ", ".join(signatures))
    return {"inspected": True, "needed": sorted(needed), "network_imports": network, "external_codec_signatures": signatures}


def classify_member(name: str, mode: str) -> dict:
    if name.startswith(NOTICE_PREFIX):
        return classify_source(name[len(NOTICE_PREFIX):])
    if name.endswith(".so"):
        return native_components()
    if mode == "classes" and name.startswith("dev/unicornwhodev/mp3codec/") and name.endswith(".class"):
        return classification("compiled_original_project_mit", ["MIT"], "Compiled project Kotlin API; no kotlin/ or external codec classes are merged into classes.jar.")
    if mode == "sources":
        if name.startswith("native/"):
            return classify_source("encoder-android/src/main/cpp/" + name[len("native/"):])
        if name.startswith("dev/") and name.endswith(".kt"):
            return classify_source("encoder-android/src/main/kotlin/" + name)
    if mode == "apk" and re.fullmatch(r"classes\d*\.dex", name):
        return classification("compiled_application_with_kotlin_runtime", ["MIT", "Apache-2.0", "BSD-3-Clause", "BSL-1.0"], "Project API/sample plus Kotlin JVM runtime and its attributed permissive portions; not a claim of byte-level ownership attribution within DEX.")
    if name == "classes.jar":
        return classification("java_archive_container", ["MIT", "LicenseRef-contained-notices"], "Each nested entry is separately inventoried.")
    if name.startswith("META-INF/") or name in {"AndroidManifest.xml", "R.txt", "proguard.txt", "resources.arsc", "kotlin-tooling-metadata.json"}:
        return classification("generated_build_metadata", ["MIT"], "Generated project/resource/signing metadata; third-party notice entries are classified separately.")
    if mode == "apk" and (name.startswith("res/") or name.endswith(".kotlin_builtins")):
        return classification("generated_application_resource", ["MIT" if name.startswith("res/") else "Apache-2.0"], "Compiled project Android resource or Kotlin runtime metadata.")
    return classification("unreviewed_archive_entry", [], "Archive entry requires explicit provenance review.")


def inspect_archive(path: Path, mode: str, root: Path, readelf: str | None, errors: list[str]) -> dict:
    content = path.read_bytes()
    result = {"path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path), "bytes": len(content), "sha256": sha256(content), "kind": mode, "entries": []}
    notices = required_notices(root)
    seen_notices, source_entries, native_entries = {}, {}, []

    def walk(blob: bytes, context: str, prefix: str = "") -> None:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
            if len(names) != len(set(names)):
                errors.append(str(path) + " contains duplicate archive entries.")
            for name in sorted(names):
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                    errors.append(str(path) + " has an unsafe archive path: " + name)
                data = archive.read(name)
                info = {"path": prefix + name, "bytes": len(data), "sha256": sha256(data), **classify_member(name, context)}
                if info["license_class"].startswith("unreviewed"):
                    errors.append(str(path) + " has an unclassified entry: " + prefix + name)
                if name.startswith(NOTICE_PREFIX):
                    relative = name[len(NOTICE_PREFIX):]
                    seen_notices[relative] = data
                    info["matches_source_notice"] = relative in notices and data == notices[relative]
                    if not info["matches_source_notice"]:
                        errors.append(str(path) + " contains a stale/unrecognized notice: " + relative)
                if name.endswith(".so"):
                    native_entries.append(name)
                    info["elf"] = inspect_elf(data, readelf, errors, str(path) + "!" + name)
                if context == "sources":
                    if name.startswith("native/"):
                        source_entries["encoder-android/src/main/cpp/" + name[len("native/"):]] = data
                    elif name.startswith("dev/") and name.endswith(".kt"):
                        source_entries["encoder-android/src/main/kotlin/" + name] = data
                result["entries"].append(info)
                if context == "aar" and name == "classes.jar":
                    walk(data, "classes", prefix + "classes.jar!")

    walk(content, mode)
    mandatory = set(notices)
    if mode == "sources":
        expected_sources = [p for base in ("encoder-android/src/main/cpp", "encoder-android/src/main/kotlin") for p in (root / base).rglob("*") if p.is_file()]
        for source in expected_sources:
            relative = source.relative_to(root).as_posix()
            if source_entries.get(relative) != source.read_bytes():
                errors.append(str(path) + " has missing/stale published source: " + relative)
        result["source_files_compared"] = len(expected_sources)
    for missing in sorted(mandatory - set(seen_notices)):
        errors.append(str(path) + " is missing a current license notice: " + missing)
    if mode in {"aar", "apk"}:
        base = "jni" if mode == "aar" else "lib"
        expected = {f"{base}/{abi}/libuwdev_mp3codec.so" for abi in ("arm64-v8a", "armeabi-v7a", "x86_64")}
        if set(native_entries) != expected:
            errors.append(str(path) + " contains an unexpected native library set.")
    result["notice_files_compared"] = len(seen_notices)
    return result


def inspect_publication(directory: Path, root: Path, readelf: str | None, errors: list[str]) -> list[dict]:
    results = []
    if not directory.is_dir():
        errors.append("Maven staging publication is missing: " + str(directory))
        return results
    for path in sorted(directory.iterdir()):
        if path.name.endswith("-sources.jar"):
            results.append(inspect_archive(path, "sources", root, readelf, errors))
        elif path.suffix == ".aar":
            results.append(inspect_archive(path, "aar", root, readelf, errors))
        elif path.suffix in {".pom", ".module"} or path.name == "maven-metadata.xml" or path.suffix in {".sha256", ".sha512", ".sha1", ".md5"}:
            data = path.read_bytes()
            row = {"path": path.relative_to(root).as_posix(), "bytes": len(data), "sha256": sha256(data), **classification("generated_publication_metadata", ["MIT"], "Generated from the project's Maven publication; declared external dependencies are recorded separately.")}
            if path.suffix == ".pom":
                ns = {"m": "http://maven.apache.org/POM/4.0.0"}
                tree = ET.fromstring(data)
                dependencies = [":".join(node.findtext("m:" + key, default="", namespaces=ns) for key in ("groupId", "artifactId", "version")) for node in tree.findall("m:dependencies/m:dependency", ns)]
                row["dependencies"] = dependencies
                if dependencies != ["org.jetbrains.kotlin:kotlin-stdlib:2.2.21"]:
                    errors.append("Published dependencies changed and require review: " + repr(dependencies))
            if path.suffix == ".module":
                for variant in json.loads(data).get("variants", []):
                    for artifact in variant.get("files", []):
                        target = directory / artifact["url"]
                        if not target.exists() and "-SNAPSHOT" in artifact["url"]:
                            component=json.loads(data)["component"]
                            original=component["module"]+"-"+component["version"]
                            if artifact["url"].startswith(original):
                                target=directory/(path.stem+artifact["url"][len(original):])
                        if not target.is_file() or sha256(target.read_bytes()) != artifact.get("sha256"):
                            errors.append("Stale Maven module checksum: " + artifact["url"])
            results.append(row)
        else:
            errors.append("Unreviewed Maven publication file: " + str(path))
    if not any(path.name.endswith("-sources.jar") for path in directory.iterdir()):
        errors.append("Published sources JAR is missing.")
    if not any(path.suffix == ".pom" for path in directory.iterdir()):
        errors.append("Published POM is missing.")
    return results


def dependency_inventory() -> list[dict]:
    return [
        {"component": "minimp3 numerical data", "revision": MINIMP3_COMMIT, "license_components": ["CC0-1.0"], "distribution": "Only attributed numeric tables; decoder source/implementation is not distributed or linked."},
        {"component": "pl_mpeg synthesis window", "revision": PL_MPEG_COMMIT, "license_components": ["MIT"], "distribution": "Only 512 attributed numeric coefficients; decoder implementation is not distributed or linked."},
        {"component": "Gradle wrapper", "version": "8.13", "license_components": ["Apache-2.0"], "distribution": "Build launchers and wrapper JAR in source distribution; not Android runtime code."},
        {"component": "Android NDK libc++ and support runtime", "version": "27.2.12479018 (r27c)", "license_components": ["Apache-2.0 WITH LLVM-exception", "LicenseRef-NDK-r27c-aggregate-notices"], "distribution": "Statically incorporated in each native Android library; entire upstream LLVM notice retained."},
        {"component": "org.jetbrains.kotlin:kotlin-stdlib", "version": "2.2.21", "revision": KOTLIN_COMMIT, "artifact_declared_license": "Apache-2.0", "license_components": ["Apache-2.0", "BSD-3-Clause", "BSL-1.0"], "jar_sha256": "6558a3d233da56a20934b32159f9db5f86ed5816ef098f78a2c223dc6abb79dd", "pom_sha256": "cf31f923196c63aedecd0a57c24269bd3702a4e47c0bf0bd64b5ada5de522272", "distribution": "External Maven dependency of AAR; JVM runtime incorporated by sample APK build. Kotlin attribution, GWT/Guava, ThreeTenBP and Boost notices retained."},
        {"component": "org.jetbrains:annotations", "version": "13.0", "license_components": ["Apache-2.0"], "jar_sha256": "ace2a10dc8e2d5fd34925ecac03e4988b2c0f851650c94b8cef49ba1bd111478", "pom_sha256": "965aeb2bedff369819bdde1bf7a0b3b89b8247dd69c88b86375d76163bb8c397", "distribution": "Transitive Kotlin JVM dependency; not merged into AAR classes.jar."},
        {"component": "Android Gradle plugin / Kotlin Gradle plugin / Android SDK / JDK / CMake / Ninja", "distribution": "External build tools and their wider dependency graphs are not redistributed in this source/AAR audit scope. Build network access is separate from Android runtime behavior."},
        {"component": "FFmpeg and mpg123", "distribution": "External independent validation processes/libraries only; their executable/library/source bytes are not redistributed in the reviewed source, AAR or sample APK."},
        {"component": "NumPy / SciPy / JUnit / AndroidX Test", "distribution": "External development/test dependencies, outside production source and library AAR. An instrumentation test APK is a separate test artifact, not a library runtime dependency."},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("build/license-audit/report.json"))
    parser.add_argument("--source-only", action="store_true", help="Explicitly omit compiled artifact inspection; report will identify this reduced scope.")
    parser.add_argument("--aar", type=Path, default=Path("encoder-android/build/outputs/aar/encoder-android-release.aar"))
    parser.add_argument("--publication-dir", type=Path, default=Path("encoder-android/build/staging-repository/io/github/unicornwhodev/uwdev-mp3codec/0.2.0"))
    parser.add_argument("--apk", type=Path, default=Path("sample-app/build/outputs/apk/debug/sample-app-debug.apk"))
    parser.add_argument("--readelf", default=shutil.which("readelf"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    errors: list[str] = []
    rows, excluded = inventory_sources(root, errors)
    production = scan_production(root, rows, errors)
    artifacts = []
    if not args.source_only:
        try:
            for option, mode in ((args.aar, "aar"), (args.apk, "apk")):
                path = option if option.is_absolute() else root / option
                if not path.is_file():
                    errors.append("Required distribution artifact missing: " + str(path))
                else:
                    artifacts.append(inspect_archive(path, mode, root, args.readelf, errors))
            publication = args.publication_dir if args.publication_dir.is_absolute() else root / args.publication_dir
            artifacts.extend(inspect_publication(publication, root, args.readelf, errors))
        except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
            errors.append("Artifact inspection failed: " + str(error))
    for row in rows:
        path = root / row["path"]
        if not path.is_file() or sha256(path.read_bytes()) != row["sha256"]:
            errors.append("Source changed during audit; rerun after edits stop: " + row["path"])
    final_paths, _ = source_files(root)
    if {path.relative_to(root).as_posix() for path in final_paths} != {row["path"] for row in rows}:
        errors.append("Source file set changed during audit or contains an unreviewed symlink; rerun after edits stop.")
    for artifact in artifacts:
        path = Path(artifact["path"])
        path = path if path.is_absolute() else root / path
        if not path.is_file() or sha256(path.read_bytes()) != artifact["sha256"]:
            errors.append("Artifact changed during audit; rerun after packaging stops: " + artifact["path"])
    serialized_inventory = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    report = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_SCOPED_CHECKS" if not errors else "REVIEW_REQUIRED",
        "passed": not errors,
        "scope": "source-only" if args.source_only else "source, release AAR, sample APK, staging Maven publication and nested archive entries",
        "source_file_count": len(rows),
        "source_license_class_counts": dict(sorted(Counter(row["license_class"] for row in rows).items())),
        "source_inventory_sha256": sha256(serialized_inventory),
        "files": rows,
        "production_checks": production,
        "artifacts": artifacts,
        "dependencies": dependency_inventory(),
        "excluded_generated_evidence": {"path_prefixes": ["docs/results/","docs/baseline-delivery/","artifacts/","root *.log"], "files_present": excluded, "reason": "Historical delivery artifacts and execution logs are evidence, not current source. Their own preserved manifests record integrity. Build/caches/local configuration are excluded; fresh AAR, APK and Maven publication are inspected explicitly."},
        "limitations": [
            "Technical provenance and packaging review only; not a legal opinion, patent clearance, or ISO certification.",
            "An original-MIT classification records project authorship declarations and inspected implementation history; hashes and keyword scans alone cannot prove independent creation or detect all unattributed copying.",
            "No known GPL/LGPL/AGPL encoder/decoder implementation is incorporated in the reviewed production sources or declared native dependencies; this is a scoped finding, not a universal software-composition proof.",
            "The retained NDK notice covers more components than the linker necessarily selected; exact object-level license attribution is not reconstructed from stripped ELF files.",
            "Maven/build dependencies are separately identified; the complete external build-tool transitive graph and instrumentation APK are outside the distributed library/source audit scope.",
            "Rerun after all final source/notice edits and final Android packaging. Final ZIP integrity is covered by its separate SHA256SUMS, not a recursive self-hash.",
        ],
        "issues": sorted(set(errors)),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix="license-audit-", suffix=".tmp", delete=False) as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)
    print(f"{report['status']}: {len(rows)} source files, {len(artifacts)} artifacts; {output}")
    for issue in report["issues"]:
        print("REVIEW:", issue)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
