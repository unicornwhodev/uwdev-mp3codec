#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Boundary and reservoir validation with independent FFmpeg and mpg123 decoders.

Tiny signals are tested for structural integrity and tail retention, not given
perceptual-quality or sample-accurate claims. Only test tools import this file.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import shutil
import sys
import numpy as np
from verify_audio import Mpg123, decode_ffmpeg, parse_mp3, reference_pcm, audio_metrics


def encode_and_decode(encoder: Path, directory: Path, name: str, pcm: np.ndarray,
                      rate: int, channels: int, kbps: int, decoder: Mpg123, block: int) -> tuple[dict,np.ndarray,np.ndarray]:
    src, dst = directory/(name+'.pcm'), directory/(name+'.mp3')
    pcm.tofile(src)
    process = subprocess.run([str(encoder),str(src),str(dst),str(rate),str(channels),str(kbps),str(block)],capture_output=True,text=True)
    if process.returncode:
        raise RuntimeError(process.stderr)
    stats=json.loads(process.stdout)
    output_rate=48000 if rate==96000 else rate
    data=dst.read_bytes()
    structure=parse_mp3(data,output_rate,channels,kbps)
    autodetect_error=None
    try:
        first,_=decode_ffmpeg(dst,channels)
    except RuntimeError as error:
        # Explicit diagnostic fallback. This does NOT convert an automatic
        # format-identification failure into a passing compatibility test.
        autodetect_error=str(error)
        diagnostic=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-v','error','-xerror',
                                   '-f','mp3','-i',str(dst),'-map','0:a:0','-f','f32le',
                                   '-acodec','pcm_f32le','-'],capture_output=True)
        if diagnostic.returncode or diagnostic.stderr:
            raise RuntimeError(autodetect_error+'; explicit MP3 decoding also failed: '+diagnostic.stderr.decode(errors='replace'))
        first=np.frombuffer(diagnostic.stdout,dtype='<f4').astype(np.float64).reshape(-1,channels)
    second=decoder.decode(dst,output_rate,channels)
    reference=reference_pcm(pcm,rate)
    assert len(first)==structure['decoded_samples_expected']==len(second), 'Decoded frame count mismatch'
    assert np.isfinite(first).all() and np.isfinite(second).all(), 'Nonfinite decoder output'
    assert stats['input_frames']==len(pcm) and stats['output_bytes']==len(data), 'Counter mismatch'
    expected_frames=max(7,(len(reference)+1151)//1152+1)
    assert len(first)==expected_frames*1152, 'Tail storage/duration mismatch'
    row={'input_sample_rate':rate,'channels':channels,'bitrate_kbps':kbps,'input_frames':len(pcm),
         'mpeg':structure,'encoding':stats,'sha256':hashlib.sha256(data).hexdigest(),
         'decoder_difference_peak':float(np.max(np.abs(first-second))),
         'independent_decoding_pass':True,'ffmpeg_autodetect_pass':autodetect_error is None}
    if autodetect_error is not None:
        row['ffmpeg_autodetect_error']=autodetect_error
        row['ffmpeg_explicit_format_diagnostic_pass']=True
    src.unlink()
    return row, first, reference


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--encoder',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('build/validation-edges'))
    parser.add_argument('--short-only',action='store_true')
    args=parser.parse_args()
    args.encoder=args.encoder.resolve()
    args.output.mkdir(parents=True,exist_ok=True)
    source_encoder=args.encoder
    args.encoder=(args.output/'encoder-under-test').resolve()
    shutil.copy2(source_encoder,args.encoder)
    encoder_sha256=hashlib.sha256(args.encoder.read_bytes()).hexdigest()
    decoder=Mpg123()
    rows=[]
    def save() -> None:
        report={'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'suite':'short_sources_and_reservoir','environment':{'system':platform.platform(),'python':sys.version,'second_decoder':decoder.name,'encoder_sha256':encoder_sha256},
                'notes':['Tail retention is an amplitude/energy and location check; it is not a perceptual-quality claim.',
                         'The known 1056-sample MPEG analysis/synthesis delay is not hidden by fitted gain.',
                         'Tiny nonempty files have a minimum of seven MPEG frames for reliable raw-format probing; this adds terminal padding only.'],
                'passed':sum(x['pass'] for x in rows),'total':len(rows),'rows':rows}
        (args.output/'report.json.part').write_text(json.dumps(report,indent=2)+'\n')
        (args.output/'report.json.part').replace(args.output/'report.json')
    for rate in [44100,48000,96000]:
        for channels in [1,2]:
            for kbps in [128,192,256,320]:
                for length in [1,7,575,576,577,1151,1152,1153]:
                    name=f'{rate}_{channels}_{kbps}_tail_{length}'
                    row={'case':name}
                    try:
                        pcm=np.zeros((length,channels),dtype='<i2')
                        pcm[-1,0]=24576
                        if channels==2:
                            pcm[-1,1]=-16384
                        details,decoded,reference=encode_and_decode(args.encoder,args.output,name,pcm,rate,channels,kbps,decoder,1)
                        row.update(details)
                        # The impulse (or independently filtered impulse) must
                        # survive in the output after the documented delay.
                        expected_peak=int(np.argmax(np.abs(reference[:,0])))+1056
                        measured_peak=int(np.argmax(np.abs(decoded[:,0])))
                        window_first=max(0,expected_peak-192)
                        window_last=min(len(decoded),expected_peak+193)
                        observed_energy=float(np.sum(decoded[window_first:window_last]**2))
                        reference_energy=float(np.sum(reference**2))
                        ratio=observed_energy/reference_energy
                        assert abs(measured_peak-expected_peak)<=8, 'Last input impulse displaced outside expected tail'
                        assert ratio>0.1, 'Last input impulse energy was lost'
                        row['tail']={'expected_peak_sample':expected_peak,'measured_peak_sample':measured_peak,
                                     'retained_energy_ratio':ratio,'decoded_peak':float(np.max(np.abs(decoded)))}
                        row['tail_retention_pass']=True
                        assert row['ffmpeg_autodetect_pass'], row['ffmpeg_autodetect_error']
                        row['pass']=True
                    except Exception as exc:
                        row['pass']=False;row['error']=str(exc)
                    rows.append(row)
                    save()
                    if not row['pass']: print('FAIL',name,row['error'],flush=True)
                print(f'Boundary cases complete: {rate}Hz {channels}ch {kbps}kbps ({sum(x["pass"] for x in rows)}/{len(rows)})',flush=True)
    if not args.short_only:
        for rate in [44100,48000,96000]:
            for kbps in [128,192,256,320]:
                channels=2
                name=f'{rate}_2_{kbps}_reservoir_stress'
                row={'case':name}
                try:
                    n=rate*4
                    t=np.arange(n)/rate
                    rng=np.random.default_rng(874254)
                    segment=(np.arange(n)//max(1,rate//10))%4
                    pcm=np.zeros((n,2),dtype=np.float64)
                    for ch,freq in [(0,997.0),(1,733.0)]:
                        tone=0.45*np.sin(2*np.pi*freq*t)
                        noise=np.clip(rng.normal(0,0.15,n),-0.9,0.9)
                        pcm[:,ch]=np.where(segment==0,0,np.where(segment==1,tone,np.where(segment==2,noise,tone+0.3*noise)))
                    pcm=np.rint(np.clip(pcm,-0.999,0.999)*32768).astype('<i2')
                    details,decoded,reference=encode_and_decode(args.encoder,args.output,name,pcm,rate,channels,kbps,decoder,137)
                    row.update(details)
                    assert row['mpeg']['reservoir_frames']>0, 'Reservoir was never used'
                    assert row['mpeg']['max_reservoir_bytes']<=511
                    assert {1,2,3}.issubset(set(row['mpeg']['block_types'])), 'Stress source did not exercise transient block transitions'
                    row['audio_observations']=audio_metrics(reference,decoded,48000 if rate==96000 else rate)
                    assert row['ffmpeg_autodetect_pass'], row['ffmpeg_autodetect_error']
                    row['pass']=True
                except Exception as exc:
                    row['pass']=False;row['error']=str(exc)
                rows.append(row);save()
                print(('PASS' if row['pass'] else 'FAIL'),name,row.get('error',''),flush=True)
    return 0 if all(x['pass'] for x in rows) else 1

if __name__=='__main__':
    raise SystemExit(main())
