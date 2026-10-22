#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the shipped ABIs, native imports/exports and 16 KiB ELF alignment."""
import argparse
import io
import json
import pathlib
import subprocess
import tempfile
import zipfile


def inspect(aar: pathlib.Path, readelf: str) -> dict:
    required = {"arm64-v8a", "armeabi-v7a", "x86_64"}
    report = {"aar": aar.name, "aar_bytes": aar.stat().st_size, "native": []}
    with zipfile.ZipFile(aar) as archive, tempfile.TemporaryDirectory(prefix="uwdev-aar-") as directory:
        with zipfile.ZipFile(io.BytesIO(archive.read("classes.jar"))) as classes:
            notices = [name for name in classes.namelist() if name.startswith("META-INF/uwdev-mp3codec/") and not name.endswith("/")]
            mandatory = {
                "META-INF/uwdev-mp3codec/LICENSE",
                "META-INF/uwdev-mp3codec/NOTICE.md",
                "META-INF/uwdev-mp3codec/third-party-notices/pl_mpeg-MIT.txt",
                "META-INF/uwdev-mp3codec/third-party-notices/Android-NDK-r27c-LLVM-NOTICE.txt",
            }
            if not mandatory.issubset(notices):
                raise ValueError(f"Missing bundled license notices: {mandatory - set(notices)}")
            report["license_notices"] = sorted(notices)
        paths = [name for name in archive.namelist() if name.startswith("jni/") and name.endswith(".so")]
        expected = {f"jni/{abi}/libuwdev_mp3codec.so" for abi in required}
        if set(paths) != expected:
            raise ValueError(f"Expected exactly one native library per ABI: {paths}")
        for path in sorted(paths):
            target = pathlib.Path(directory) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(path)
            target.write_bytes(data)
            headers = subprocess.check_output([readelf, "-W", "-l", str(target)], text=True)
            loads = [line.split() for line in headers.splitlines() if line.strip().startswith("LOAD ")]
            if not loads or any(int(fields[-1], 16) < 16384 for fields in loads):
                raise ValueError(f"Insufficient ELF LOAD alignment for {path}: {loads}")
            if any((int(fields[1], 16) - int(fields[2], 16)) % 16384 != 0 for fields in loads):
                raise ValueError(f"Incongruent ELF segment offset/address for {path}")
            symbols = subprocess.check_output([readelf, "-W", "--dyn-syms", str(target)], text=True)
            exports = []
            for line in symbols.splitlines():
                fields = line.split()
                if len(fields) >= 8 and fields[4] in ("GLOBAL", "WEAK") and fields[5] == "DEFAULT" and fields[6] not in ("UND", "ABS"):
                    exports.append(fields[7])
            if exports != ["JNI_OnLoad"]:
                raise ValueError(f"Unexpected dynamic exports for {path}: {exports}")
            dynamic = subprocess.check_output([readelf, "-W", "-d", str(target)], text=True)
            imports = [line.split("[", 1)[1].split("]", 1)[0] for line in dynamic.splitlines() if "(NEEDED)" in line]
            for dependency in imports:
                if dependency not in {"libc.so", "libm.so", "libdl.so", "liblog.so", "libandroid.so"}:
                    raise ValueError(f"Unexpected runtime dependency in {path}: {dependency}")
            report["native"].append({"abi": path.split("/")[1], "bytes": len(data), "elf_load_alignments": [int(x[-1], 16) for x in loads], "exports": exports, "needed": imports})
    report["passed"] = True
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("aar", type=pathlib.Path)
    parser.add_argument("--readelf", default="readelf")
    parser.add_argument("--report", type=pathlib.Path)
    arguments = parser.parse_args()
    result = inspect(arguments.aar, arguments.readelf)
    serialized = json.dumps(result, indent=2) + "\n"
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(serialized)
    print(serialized, end="")
