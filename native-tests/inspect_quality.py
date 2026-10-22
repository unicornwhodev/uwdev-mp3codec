#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Additional diagnostics on existing outputs; never changes encoding or gates.

Reconstructs the same deterministic test fixtures independently of the codec,
decodes existing MP3s, and reports matched-interval dynamics, pre-impulse error,
and tone-isolation measurements. This is not a perceptual transparency test.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import math
import pathlib
import numpy as np
import verify_audio


def db20(value: float) -> float:
    return 20*math.log10(max(float(value), 1e-15))


def dynamics(samples: np.ndarray, rate: int) -> dict:
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples*samples)))
    count = max(1, round(rate*0.020))
    lengths = len(samples)//count
    if lengths:
        blocks = samples[:lengths*count].reshape(lengths,count,samples.shape[1])
        block_rms = np.sqrt(np.mean(blocks*blocks,axis=(1,2)))
        levels = 20*np.log10(np.maximum(block_rms,1e-9))
        window_range = float(np.percentile(levels,95)-np.percentile(levels,10))
    else:
        window_range = None
    return {"peak":peak,"rms":rms,"rms_dbfs":db20(rms),
            "crest_db":db20(peak/rms) if rms else None,
            "rms_window_20ms_p95_p10_db":window_range}


def inspect(row: dict, directory: pathlib.Path) -> dict:
    rate,channels,kbps,name = (row[k] for k in ("input_sample_rate","channels","bitrate_kbps","signal"))
    seconds = row["encoding"]["input_frames"]/rate
    path = directory/f"{rate}_{channels}_{kbps}_{name}.mp3"
    current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if current_hash != row["sha256"]:
        raise RuntimeError(f"MP3 evidence changed since validation: {path}; expected {row['sha256']}, observed {current_hash}")
    pcm = verify_audio.fixture(name,rate,channels,seconds)
    reference = verify_audio.reference_pcm(pcm,rate)
    output_rate = 48000 if rate==96000 else rate
    decoded,_ = verify_audio.decode_ffmpeg(path,channels)
    lag = row["ffmpeg"]["lag_samples"]
    if lag is None:
        return {"signal":name,"input_sample_rate":rate,"channels":channels,"bitrate_kbps":kbps,
                "decoded_peak_dbfs":db20(np.max(np.abs(decoded))),"silent_reference":True}
    length = min(len(reference),len(decoded)-lag)
    trim = min(output_rate//5,length//5)
    source = reference[trim:length-trim]
    matched = decoded[lag+trim:lag+length-trim]
    source_dynamics, decoded_dynamics = dynamics(source,output_rate),dynamics(matched,output_rate)
    result = {"signal":name,"input_sample_rate":rate,"channels":channels,"bitrate_kbps":kbps,
              "alignment_samples":lag,"source":source_dynamics,"decoded":decoded_dynamics,
              "rms_gain_db":db20(decoded_dynamics["rms"]/source_dynamics["rms"]) if source_dynamics["rms"] else None,
              "crest_change_db":decoded_dynamics["crest_db"]-source_dynamics["crest_db"] if source_dynamics["crest_db"] is not None else None,
              "full_decoded_samples_above_1":int(np.count_nonzero(np.abs(decoded)>1)),
              "full_decoded_peak":float(np.max(np.abs(decoded)))}
    if name=="impulse":
        activity = np.max(np.abs(reference),axis=1)
        threshold = float(activity.max())*1e-4
        onset = int(np.flatnonzero(activity>threshold)[0])
        begin = max(0,onset-round(.020*output_rate))
        a = reference[begin:onset]
        b = decoded[lag+begin:lag+onset]
        error = b-a
        pre_energy = float(np.sum(error*error))
        signal_energy = float(np.sum(reference*reference))
        result["pre_impulse_error"] = {
            "window_samples":onset-begin,
            "window_ms":1000*(onset-begin)/output_rate,
            "reference_onset_threshold_relative":1e-4,
            "peak_dbfs":db20(np.max(np.abs(error))) if error.size else None,
            "energy_relative_to_impulse_db":10*math.log10(max(pre_energy,1e-30)/max(signal_energy,1e-30))}
    if name=="stereo_distinct" and channels==2:
        t=np.arange(len(matched))/output_rate
        basis=np.column_stack([np.sin(2*np.pi*1000*t),np.cos(2*np.pi*1000*t),
                               np.sin(2*np.pi*733*t),np.cos(2*np.pi*733*t),np.ones(len(t))])
        coefficients=np.linalg.lstsq(basis,matched,rcond=None)[0]
        left_wanted=float(np.hypot(coefficients[0,0],coefficients[1,0]))
        left_other=float(np.hypot(coefficients[2,0],coefficients[3,0]))
        right_wanted=float(np.hypot(coefficients[2,1],coefficients[3,1]))
        right_other=float(np.hypot(coefficients[0,1],coefficients[1,1]))
        result["tone_isolation_db"]={"733_hz_in_left_relative_to_1000":db20(left_other/max(left_wanted,1e-15)),
                                     "1000_hz_in_right_relative_to_733":db20(right_other/max(right_wanted,1e-15))}
    return result


def write_review(path: pathlib.Path, report: dict, evidence: dict) -> None:
    rows=evidence["rows"]
    selected=[r for r in rows if r["channels"]==2 and r["bitrate_kbps"]==192 and r["signal"] in ("white_noise","pink_noise","percussion","composition")]
    source={(r["input_sample_rate"],r["channels"],r["bitrate_kbps"],r["signal"]):r for r in report["rows"]}
    lines=["# Independent quality review", "", f"Generated: {evidence['generated_utc']}", "",
           "This is a numerical review of existing MP3 outputs. It is not a subjective listening assessment, an ISO certification, or a transparency claim.", "",
           f"The input report contains {report['total']} cases ({report['passed']} pass its stated structural/sine gates). Supplemental diagnostics cover {len(rows)} existing outputs. No files were re-encoded for this review.", "",
           "## Default bitrate, conventional stereo", "",
           "SNR uses aligned samples without gain fitting, DC removal, or normalization. For 96 kHz input, the independent reference includes the required 192-tap Kaiser anti-alias filter and decimation; its SNR therefore measures error relative to that filtered 48 kHz signal.", "",
           "| Input rate | Signal | SNR (dB) | RMS gain (dB) | Crest change (dB) | 20 ms RMS range, source / decoded (dB) |", "|---:|---|---:|---:|---:|---:|"]
    for r in selected:
        original=source[r["input_sample_rate"],r["channels"],r["bitrate_kbps"],r["signal"]]
        lines.append(f"| {r['input_sample_rate']} | {r['signal']} | {original['ffmpeg']['snr_db']:.2f} | {r['rms_gain_db']:+.3f} | {r['crest_change_db']:+.3f} | {r['source']['rms_window_20ms_p95_p10_db']:.2f} / {r['decoded']['rms_window_20ms_p95_p10_db']:.2f} |")
    lines += ["", "The 20 ms RMS range is the difference between the 95th and 10th percentiles of windowed RMS levels. It is a diagnostic of this fixture, not a standardized mastering dynamic-range score. Noise and percussion can have substantially lower waveform SNR than a steady sine even when both decode correctly.", "", "## Transient error", "",
              "The impulse diagnostic measures the error in the 20 ms before the reference first exceeds 0.01% of its peak. It compares with the expected FIR response at 96 kHz. Values include quantization, polyphase reconstruction error, and possible pre-echo; they do not independently establish audibility.", "",
              "| Input rate | Bitrate | Channels | Pre-impulse error peak (dBFS) | Error energy / impulse energy (dB) |", "|---:|---:|---:|---:|---:|"]
    for r in rows:
        if r["signal"]=="impulse" and r["channels"]==2 and r["bitrate_kbps"]==192:
            q=r["pre_impulse_error"]
            lines.append(f"| {r['input_sample_rate']} | {r['bitrate_kbps']} | {r['channels']} | {q['peak_dbfs']:.2f} | {q['energy_relative_to_impulse_db']:.2f} |")
    overshoot=[r for r in rows if r["signal"]=="fullscale"]
    lines += ["", "## Headroom and channel isolation", ""]
    if overshoot:
        maximum=max(r["full_decoded_peak"] for r in overshoot)
        lines.append(f"The full-scale sine produced a maximum decoded floating-point peak of **{maximum:.6f}** ({db20(maximum):+.3f} dBFS) across the measured configurations. Samples above 1.0 are counted in the JSON report. Such overshoots can clip in an integer-output player. The library does not apply an unrequested limiter or normalize the caller's signal; allow source headroom when this matters.")
    lines += ["", "| Input rate | Left: unwanted 733 Hz / wanted 1 kHz (dB) | Right: unwanted 1 kHz / wanted 733 Hz (dB) |", "|---:|---:|---:|"]
    for r in rows:
        if r["signal"]=="stereo_distinct" and r["channels"]==2 and r["bitrate_kbps"]==192:
            q=r["tone_isolation_db"]
            lines.append(f"| {r['input_sample_rate']} | {q['733_hz_in_left_relative_to_1000']:.2f} | {q['1000_hz_in_right_relative_to_733']:.2f} |")
    lines += ["", "Channel isolation uses a two-tone least-squares diagnostic on the aligned stable interval. This fit is used only to estimate unwanted tone amplitudes; it is not applied to the SNR measurement.", "", "## Interpretation and remaining work", "",
              "The codec has a simple local masking model and conventional stereo. Broadband-noise loss and transient errors warrant further tuning and controlled listening tests before describing this encoder as transparent or comparable to mature MP3 implementations. These measurements do not demonstrate Android ARM64 performance, battery use, or thermal behavior.", "",
              "Reproduce after the full validation suite:", "", "```sh", f"python3 native-tests/inspect_quality.py --validation {evidence['validation_directory']} --markdown docs/QUALITY_REVIEW.md", "```", "",
              f"Detailed results: `{evidence['validation_directory']}/supplemental-quality.json` (generated evidence, not a production dependency).", ""]
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+".part")
    temporary.write_text("\n".join(lines))
    temporary.replace(path)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--validation",required=True,type=pathlib.Path)
    ap.add_argument("--markdown",type=pathlib.Path)
    args=ap.parse_args()
    report=json.loads((args.validation/"report.json").read_text())
    chosen=[r for r in report["rows"] if r.get("structural_pass")]
    evidence={"generated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "validation_directory":str(args.validation),
              "report_total":report["total"],"complete_full_matrix":report["total"]==264,
              "normalization":"none; matched reference interval, original amplitude", "rows":[]}
    for row in chosen:
        evidence["rows"].append(inspect(row,args.validation))
    output=args.validation/"supplemental-quality.json"
    temporary=output.with_name(output.name+".part")
    temporary.write_text(json.dumps(evidence,indent=2)+"\n")
    temporary.replace(output)
    if args.markdown:write_review(args.markdown,report,evidence)
    print(f"Supplemental diagnostics: {len(evidence['rows'])} files; full matrix complete: {evidence['complete_full_matrix']}; {output}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
