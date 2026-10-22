#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host validation only: independent PCM fixtures, frame parser, FFmpeg + mpg123.

The Android library does not import or link any of these test dependencies.
Install numpy/scipy, FFmpeg and libmpg123 before running this script.
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.util
import datetime
import hashlib
import json
import math
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import time
import numpy as np
from scipy import signal


class Bits:
    def __init__(self, value: bytes):
        self.value, self.pos = value, 0

    def get(self, n: int) -> int:
        assert self.pos + n <= len(self.value) * 8, "Side information overrun"
        result = 0
        for _ in range(n):
            result = (result << 1) | ((self.value[self.pos // 8] >> (7 - self.pos % 8)) & 1)
            self.pos += 1
        return result


def parse_mp3(data: bytes, rate: int, channels: int, kbps: int) -> dict:
    pos, frames, previous_capacity, previous_audio_end = 0, [], 0, 0
    while pos < len(data):
        assert pos + 4 <= len(data), "Truncated MPEG header"
        h = int.from_bytes(data[pos:pos+4], "big")
        assert h >> 21 == 0x7ff, f"MPEG sync missing at {pos}"
        assert (h >> 19) & 3 == 3, "Must be MPEG-1"
        assert (h >> 17) & 3 == 1, "Must be Layer III"
        assert (h >> 16) & 1 == 1, "CRC must be absent"
        br = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0][(h >> 12) & 15]
        sr = [44100,48000,32000,0][(h >> 10) & 3]
        ch = 1 if ((h >> 6) & 3) == 3 else 2
        assert (br, sr, ch) == (kbps, rate, channels), "Header configuration mismatch"
        assert (h >> 6) & 3 == (3 if channels == 1 else 0), "Only conventional mono/stereo allowed"
        assert h & 3 == 0 and (h >> 2) & 3 == 0, "Emphasis/copyright/original flags"
        padding = (h >> 9) & 1
        length = 144000 * br // sr + padding
        assert pos + length <= len(data), "Truncated MPEG frame"
        side_len = 17 if channels == 1 else 32
        b = Bits(data[pos+4:pos+4+side_len])
        back = b.get(9)
        b.get(5 if channels == 1 else 3)
        scfsi = [b.get(4) for _ in range(channels)]
        granules = []
        total_audio_bits = 0
        for _gr in range(2):
            for _ch in range(channels):
                part = b.get(12)
                pairs = b.get(9)
                gain, sf = b.get(8), b.get(4)
                switched = b.get(1)
                if switched:
                    block, mixed = b.get(2), b.get(1)
                    assert block != 0, "Switched block type cannot be zero"
                    tables = [b.get(5), b.get(5)]
                    subblock_gain = [b.get(3) for _ in range(3)]
                else:
                    block, mixed, subblock_gain = 0, 0, [0,0,0]
                    tables = [b.get(5) for _ in range(3)]
                    r0, r1 = b.get(4), b.get(3)
                    assert r0 + r1 + 2 <= 22, "Invalid scale-factor regions"
                pre, sfscale, count1 = b.get(1), b.get(1), b.get(1)
                assert pairs <= 288, "Too many Huffman big-value pairs"
                assert all(t not in (4,14) for t in tables), "Forbidden Huffman table"
                total_audio_bits += part
                granules.append({"part2_3_length":part,"big_values":pairs,"global_gain":gain,
                                  "scalefac_compress":sf,"block_type":block,"tables":tables})
        assert b.pos == side_len * 8
        capacity = length - 4 - side_len
        assert 0 <= back <= min(511, previous_capacity), "Reservoir back reference before stream start"
        audio_start = (previous_capacity - back) * 8
        assert audio_start >= previous_audio_end, "Overlapping main-data payloads"
        assert audio_start + total_audio_bits <= (previous_capacity + capacity) * 8, "Main data exceeds frame/reservoir budget"
        previous_audio_end = audio_start + total_audio_bits
        previous_capacity += capacity
        frames.append({"bytes":length,"main_data_begin":back,"padding":padding,"granules":granules})
        pos += length
    assert frames, "Empty MPEG stream"
    return {"frames":len(frames),"reservoir_frames":sum(f["main_data_begin"] > 0 for f in frames),
            "max_reservoir_bytes":max(f["main_data_begin"] for f in frames),
            "block_types":sorted({g["block_type"] for f in frames for g in f["granules"]}),
            "padding_frames":sum(f["padding"] for f in frames),
            "bytes":len(data),"decoded_samples_expected":len(frames)*1152}


def decode_ffmpeg(path: pathlib.Path, channels: int) -> tuple[np.ndarray,str]:
    p = subprocess.run(["ffmpeg","-hide_banner","-nostdin","-v","error","-xerror","-i",str(path),
                        "-map","0:a:0","-f","f32le","-acodec","pcm_f32le","-"], capture_output=True)
    if p.returncode or p.stderr:
        raise RuntimeError("FFmpeg decoder error: " + p.stderr.decode(errors="replace"))
    return np.frombuffer(p.stdout,dtype="<f4").astype(np.float64).reshape(-1,channels), p.stderr.decode()


class Mpg123:
    def __init__(self):
        name = os.environ.get("MPG123_LIBRARY") or ctypes.util.find_library("mpg123")
        if not name:
            raise RuntimeError("libmpg123 is required as the second independent decoder")
        self.lib = C.CDLL(name)
        self.name = name
        lib = self.lib
        lib.mpg123_init.restype = C.c_int
        lib.mpg123_new.argtypes = [C.c_char_p,C.POINTER(C.c_int)]
        lib.mpg123_new.restype = C.c_void_p
        lib.mpg123_format_none.argtypes = [C.c_void_p]
        lib.mpg123_format.argtypes = [C.c_void_p,C.c_long,C.c_int,C.c_int]
        lib.mpg123_open.argtypes = [C.c_void_p,C.c_char_p]
        lib.mpg123_getformat.argtypes = [C.c_void_p,C.POINTER(C.c_long),C.POINTER(C.c_int),C.POINTER(C.c_int)]
        lib.mpg123_read.argtypes = [C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
        lib.mpg123_close.argtypes = [C.c_void_p]
        lib.mpg123_delete.argtypes = [C.c_void_p]
        lib.mpg123_strerror.argtypes = [C.c_void_p]
        lib.mpg123_strerror.restype = C.c_char_p
        assert lib.mpg123_init() == 0

    def decode(self, path: pathlib.Path, rate: int, channels: int) -> np.ndarray:
        lib, error = self.lib, C.c_int()
        h = lib.mpg123_new(None,C.byref(error))
        if not h:
            raise RuntimeError(f"mpg123 handle creation failed: {error.value}")
        try:
            assert lib.mpg123_format_none(h) == 0
            # Public API constants MPG123_MONO|STEREO and MPG123_ENC_FLOAT_32.
            assert lib.mpg123_format(h,rate,3,0x200) == 0
            assert lib.mpg123_open(h,str(path).encode()) == 0
            r,c,e = C.c_long(),C.c_int(),C.c_int()
            assert lib.mpg123_getformat(h,C.byref(r),C.byref(c),C.byref(e)) == 0
            assert (r.value,c.value,e.value) == (rate,channels,0x200)
            chunks = []
            buffer = C.create_string_buffer(65536)
            while True:
                done = C.c_size_t()
                result = lib.mpg123_read(h,buffer,len(buffer),C.byref(done))
                if done.value:
                    chunks.append(buffer.raw[:done.value])
                if result == -12: # MPG123_DONE
                    break
                if result not in (0,-11): # MPG123_OK, MPG123_NEW_FORMAT
                    raise RuntimeError(lib.mpg123_strerror(h).decode())
            return np.frombuffer(b"".join(chunks),dtype="=f4").astype(np.float64).reshape(-1,channels)
        finally:
            lib.mpg123_close(h)
            lib.mpg123_delete(h)


def fixture(name: str, rate: int, channels: int, seconds: float = 1.5) -> np.ndarray:
    n = max(1, round(rate*seconds))
    t = np.arange(n,dtype=np.float64)/rate
    rng = np.random.default_rng(20261022)
    if name == "silence":
        x = np.zeros(n)
    elif name in ("sine_1000","sine_10000","stereo_distinct","fullscale"):
        f = 10000 if name == "sine_10000" else 1000
        x = (32767/32768 if name == "fullscale" else 0.5)*np.sin(2*np.pi*f*t)
    elif name == "sweep":
        x = 0.5*signal.chirp(t,50,seconds,20000,method="logarithmic")
    elif name == "impulse":
        x = np.zeros(n)
        x[min(n-1,rate//4)] = 0.9
    elif name == "white_noise":
        x = np.clip(rng.normal(0,0.15,n),-0.9,0.9)
    elif name == "pink_noise":
        spectrum = np.fft.rfft(rng.normal(0,1,n))
        spectrum /= np.sqrt(np.maximum(np.fft.rfftfreq(n),1/n))
        x = np.fft.irfft(spectrum,n=n)
        x *= 0.15/np.std(x)
        x = np.clip(x,-0.9,0.9)
    elif name == "percussion":
        beat = np.mod(t,0.2)
        x = 0.45*np.exp(-beat*50)*np.sin(2*np.pi*(80*beat+40*(1-np.exp(-beat*30))/30))
        x += 0.18*np.exp(-beat*80)*rng.uniform(-1,1,n)
    elif name == "composition":
        root = np.choose((t/0.35).astype(int)%4,[220.0,261.625565,293.664768,196.0])
        phase = np.cumsum(root)/rate
        beat = np.mod(t,0.175)
        x = 0.17*np.sin(2*np.pi*phase) + 0.12*np.sin(2*np.pi*phase*1.5)
        x += 0.08*np.sin(2*np.pi*phase*2)*np.exp(-np.mod(t,0.35)*4)
        x += 0.18*np.sin(2*np.pi*65*beat)*np.exp(-beat*35)
        x += 0.08*rng.uniform(-1,1,n)*np.exp(-beat*75)
    else:
        raise ValueError(name)
    x = np.tile(x[:,None],(1,channels))
    if channels == 2 and name == "stereo_distinct":
        x[:,1] = 0.25*np.sin(2*np.pi*733*t+0.3)
    return np.clip(np.rint(x*32768),-32768,32767).astype("<i2")


def reference_pcm(pcm: np.ndarray, input_rate: int) -> np.ndarray:
    x = pcm.astype(np.float64)/32768.0
    if input_rate != 96000:
        return x
    # Independent construction from the explicit user specification.
    taps = 2*(22000/96000)*np.sinc(2*(22000/96000)*(np.arange(192)-95.5))*np.kaiser(192,8.6)
    taps /= taps.sum()
    return np.stack([np.convolve(x[:,c],taps,mode="full")[::2] for c in range(x.shape[1])],axis=1)


def audio_metrics(source: np.ndarray, decoded: np.ndarray, rate: int) -> dict:
    if np.max(np.abs(source)) == 0:
        return {"peak":float(np.max(np.abs(decoded))),"rms":float(np.sqrt(np.mean(decoded**2))),"lag_samples":None,"snr_db":None}
    correlation = signal.correlate(decoded[:,0],source[:,0],mode="full",method="fft")
    lags = signal.correlation_lags(len(decoded),len(source))
    candidates = (lags >= 0) & (lags <= 4096)
    lag = int(lags[candidates][np.argmax(correlation[candidates])])
    length = min(len(source),len(decoded)-lag)
    trim = min(rate//5,length//5)
    a,b = source[trim:length-trim],decoded[lag+trim:lag+length-trim]
    noise = float(np.mean((a-b)**2))
    power = float(np.mean(a*a))
    snr = 10*math.log10(max(power,1e-30)/max(noise,1e-30))
    spectrum_a = np.abs(np.fft.rfft(a[:,0]*np.hanning(len(a))))
    spectrum_b = np.abs(np.fft.rfft(b[:,0]*np.hanning(len(b))))
    active = spectrum_a > spectrum_a.max()*1e-4
    spectral_mae = float(np.mean(np.abs(20*np.log10(np.maximum(spectrum_b[active],1e-12)/np.maximum(spectrum_a[active],1e-12)))))
    all_a,all_b=source[:length],decoded[lag:lag+length]
    window=min(rate//20,length)
    edges={}
    for label,region in [('begin',slice(0,window)),('end',slice(length-window,length))]:
        edges[label]={"source_rms":float(np.sqrt(np.mean(all_a[region]**2))),
                      "decoded_rms":float(np.sqrt(np.mean(all_b[region]**2))),
                      "error_rms":float(np.sqrt(np.mean((all_a[region]-all_b[region])**2)))}
    return {"lag_samples":lag,"snr_db":snr,"peak":float(np.max(np.abs(decoded))),
            "rms":float(np.sqrt(np.mean(b*b))),"source_rms":float(np.sqrt(power)),
            "gain_db":float(20*np.log10(max(abs(float(np.sum(a*b)/np.sum(a*a))),1e-30))),
            "missing_source_samples":len(source)-length,"edges_50ms":edges,
            "samples_above_fullscale":int(np.sum(np.abs(decoded)>1)),"spectral_error_db_active_bins":spectral_mae}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder",type=pathlib.Path,required=True)
    ap.add_argument("--output",type=pathlib.Path,default=pathlib.Path("validation-output"))
    ap.add_argument("--suite",choices=["matrix","signals","full"],default="matrix")
    ap.add_argument("--seconds",type=float,default=1.5)
    args = ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    # Freeze the tested executable so a concurrent Android/native rebuild
    # cannot silently change the binary midway through a validation matrix.
    frozen_encoder = args.output / ("encoder-under-test.exe" if os.name == "nt" else "encoder-under-test")
    shutil.copy2(args.encoder.resolve(), frozen_encoder)
    frozen_encoder.chmod(0o755)
    binary_hash = hashlib.sha256(frozen_encoder.read_bytes()).hexdigest()
    decoder = Mpg123()
    fixtures = ["silence","sine_1000","sine_10000","sweep","impulse","white_noise","pink_noise","stereo_distinct","percussion","composition","fullscale"]
    rows = []
    configurations = [(r,c,b) for r in [44100,48000,96000] for c in [1,2] for b in [128,192,256,320]]
    if args.suite == "signals":
        configurations = [(44100,2,192),(48000,2,192),(96000,2,192)]
    names = ["sine_1000"] if args.suite == "matrix" else fixtures
    for rate,channels,kbps in configurations:
        for name in names:
            tag = f"{rate}_{channels}_{kbps}_{name}"
            row = {"input_sample_rate":rate,"channels":channels,"bitrate_kbps":kbps,"signal":name}
            try:
                pcm = fixture(name,rate,channels,args.seconds)
                pcm_path,mp3_path = args.output/(tag+".pcm"),args.output/(tag+".mp3")
                pcm.tofile(pcm_path)
                p = subprocess.run([str(frozen_encoder.resolve()),str(pcm_path),str(mp3_path),str(rate),str(channels),str(kbps),"4096"],capture_output=True,text=True)
                if p.returncode:
                    raise RuntimeError(p.stderr)
                stats = json.loads(p.stdout)
                row["encoding"] = stats
                out_rate = 48000 if rate == 96000 else rate
                data = mp3_path.read_bytes()
                row["sha256"] = hashlib.sha256(data).hexdigest()
                row["mpeg"] = parse_mp3(data,out_rate,channels,kbps)
                ff,_ = decode_ffmpeg(mp3_path,channels)
                mpg = decoder.decode(mp3_path,out_rate,channels)
                assert len(ff) == row["mpeg"]["decoded_samples_expected"]
                assert len(mpg) == len(ff), "Independent decoder duration disagreement"
                assert stats["input_frames"] == len(pcm)
                assert stats["output_bytes"] == len(data)
                assert stats["encoded_mpeg_frames"] == row["mpeg"]["frames"]
                ref = reference_pcm(pcm,rate)
                # Exact documented transform drainage/frame rounding, plus a
                # seven-frame minimum for reliable automatic format probing.
                expected_samples = max(7, (len(ref)+1151)//1152+1)*1152
                assert len(ff) == expected_samples, "Unexpected decoded duration"
                row["ffmpeg"] = audio_metrics(ref,ff,out_rate)
                row["mpg123"] = audio_metrics(ref,mpg,out_rate)
                row["decoder_difference_peak"] = float(np.max(np.abs(ff-mpg)))
                row["structural_pass"] = True
                row["sine_snr_gate_pass"] = (name != "sine_1000" or kbps != 192 or min(row["ffmpeg"]["snr_db"],row["mpg123"]["snr_db"]) >= 30)
                # These detect silence, non-finite output, truncation or gross
                # amplitude faults on every stimulus. They are not LAME quality gates.
                gates={"finite":bool(np.isfinite(ff).all() and np.isfinite(mpg).all()),
                       "decoder_agreement_below_1e_4":row["decoder_difference_peak"]<1e-4}
                if name=='silence':
                    gates["silence_below_1e_7"]=max(row["ffmpeg"]["peak"],row["mpg123"]["peak"])<1e-7
                else:
                    gates["all_source_samples_present"]=all(row[d]["missing_source_samples"]==0 for d in ('ffmpeg','mpg123'))
                    # +/-6 dB is a deliberately broad malfunction bound, with
                    # no gain compensation in the measured waveform.
                    gates["gain_within_6db"]=all(abs(row[d]["gain_db"])<6 for d in ('ffmpeg','mpg123'))
                    gates["non_muted"]=all(row[d]["rms"]>1e-8 for d in ('ffmpeg','mpg123'))
                row["technical_gates"]={"scope":"gross technical defects only; perceptual listening not performed",**gates}
                row["pass"] = row["sine_snr_gate_pass"] and all(gates.values())
                pcm_path.unlink()
            except Exception as exc:
                row["pass"] = False
                row["error"] = str(exc)
            rows.append(row)
            print(f"{'PASS' if row['pass'] else 'FAIL'} {tag} " + (f"SNR={row.get('ffmpeg',{}).get('snr_db')}" if 'error' not in row else row['error']),flush=True)
            report = {"generated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      "environment":{"system":platform.platform(),"python":sys.version,"numpy":np.__version__,"second_decoder":decoder.name,
                                     "ffmpeg":subprocess.run(["ffmpeg","-version"],capture_output=True,text=True).stdout.splitlines()[0]},
                      "encoder_binary_sha256":binary_hash,
                      "suite":args.suite,"rows":rows,"passed":sum(r["pass"] for r in rows),"total":len(rows)}
            temporary_report = args.output/"report.json.tmp"
            temporary_report.write_text(json.dumps(report,indent=2)+"\n")
            temporary_report.replace(args.output/"report.json")
    return 0 if all(r["pass"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
