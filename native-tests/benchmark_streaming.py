#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-only long-stream measurement; it is not an Android performance claim."""
from __future__ import annotations
import argparse
import ctypes as C
import datetime
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import time
from verify_audio import Mpg123, parse_mp3


def rss_kib(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError):
        pass
    return None


def decode_count(decoder: Mpg123, path: Path) -> int:
    lib, error = decoder.lib, C.c_int()
    h = lib.mpg123_new(None,C.byref(error))
    if not h:
        raise RuntimeError("mpg123 creation failed")
    try:
        assert lib.mpg123_format_none(h) == 0
        assert lib.mpg123_format(h,44100,3,0x200) == 0
        assert lib.mpg123_open(h,str(path).encode()) == 0
        rate,channels,encoding = C.c_long(),C.c_int(),C.c_int()
        assert lib.mpg123_getformat(h,C.byref(rate),C.byref(channels),C.byref(encoding)) == 0
        assert (rate.value,channels.value,encoding.value) == (44100,2,0x200)
        total = 0
        buffer = C.create_string_buffer(65536)
        while True:
            done = C.c_size_t()
            status = lib.mpg123_read(h,buffer,len(buffer),C.byref(done))
            total += done.value
            if status == -12:
                return total//8
            if status not in (0,-11):
                raise RuntimeError(lib.mpg123_strerror(h).decode())
    finally:
        lib.mpg123_close(h)
        lib.mpg123_delete(h)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=Path("build/benchmarks"))
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    frozen = args.output/"encoder-under-test"
    shutil.copy2(args.encoder,frozen)
    frozen.chmod(0o755)
    decoder = Mpg123()
    rows = []
    cpu_model = "unknown"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        cpu_model = next((x.split(":",1)[1].strip() for x in cpuinfo.read_text().splitlines() if x.startswith("model name")),cpu_model)
    report = {"generated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "platform":platform.platform(),"cpu_model":cpu_model,
              "device":"Linux host, not Android hardware","android_version":None,"abi":platform.machine(),
              "encoder_binary_sha256":hashlib.sha256(frozen.read_bytes()).hexdigest(),
              "signal":"generated 1kHz left /733Hz right, amplitude approximately0.5; generation and file IO included",
              "rows":rows}
    for duration in (180,1800):
        target = args.output/f"stereo-44100-192-{duration}s.mp3"
        p = subprocess.Popen([str(frozen.resolve()),"--sine",str(target),"44100","2","192","4096",str(duration)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        start = time.monotonic()
        samples = []
        while p.poll() is None:
            rss = rss_kib(p.pid)
            if rss is not None:
                samples.append([round(time.monotonic()-start,4),rss])
            time.sleep(0.05)
        stdout,stderr = p.communicate()
        if p.returncode:
            raise RuntimeError(stderr)
        row = json.loads(stdout)
        row.update({"sample_rate":44100,"channels":2,"bitrate_kbps":192,"input_duration_seconds":duration,
                    "real_time_factor":row["wall_seconds"]/duration,"speed_times_realtime":duration/row["wall_seconds"],
                    "rss_samples":samples,"sampled_peak_rss_kib":max((s[1] for s in samples),default=None)})
        # Exclude initial program startup when comparing early/late resident memory.
        stable = [s[1] for s in samples if s[0] >= 0.25]
        if len(stable) >= 4:
            q = max(1,len(stable)//4)
            row["first_quarter_rss_kib"] = sum(stable[:q])/q
            row["last_quarter_rss_kib"] = sum(stable[-q:])/q
            row["rss_growth_kib"] = row["last_quarter_rss_kib"]-row["first_quarter_rss_kib"]
        data = target.read_bytes()
        row["sha256"] = hashlib.sha256(data).hexdigest()
        structure = parse_mp3(data,44100,2,192)
        row["mpeg"] = structure
        ff = subprocess.run(["ffmpeg","-hide_banner","-nostdin","-v","error","-xerror","-i",str(target),"-f","null","-"],capture_output=True,text=True)
        assert ff.returncode == 0 and not ff.stderr, ff.stderr
        decoded_samples = decode_count(decoder,target)
        assert decoded_samples == structure["decoded_samples_expected"]
        assert structure["frames"] == row["encoded_mpeg_frames"]
        assert row["input_frames"] == duration*44100
        row["ffmpeg_decoding_pass"] = True
        row["mpg123_decoding_pass"] = True
        row["pass"] = row["process_vm_hwm_kib"] < 65536
        rows.append(row)
        temporary = args.output/"report.json.tmp"
        temporary.write_text(json.dumps(report,indent=2)+"\n")
        temporary.replace(args.output/"report.json")
        print(json.dumps({k:v for k,v in row.items() if k not in ("rss_samples","mpeg")}),flush=True)
    return 0 if all(r["pass"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
