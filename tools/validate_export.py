#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Local-only facade qualification. Never publishes or configures CI/workflows."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CORE_SHA = 'dc78b3b583abc95542f3d37487b2749670f75d58edbc26d00af5c342d2f574e4'
CORE = ROOT / 'maven/io/github/unicornwhodev/uwdev-mp3codec/0.2.0/uwdev-mp3codec-0.2.0.aar'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-serial', help='Explicit ADB device; never retained in the public summary')
    parser.add_argument('--skip-build', action='store_true', help='Inspect existing outputs, recording that builds were not rerun')
    parser.add_argument('--offline', action='store_true', help='Use only cached Gradle dependencies')
    args = parser.parse_args()
    evidence = ROOT / 'build/export-validation'
    evidence.mkdir(parents=True, exist_ok=True)
    report = {'schema': 'uwdev.export-validation.v1', 'at': datetime.now(timezone.utc).isoformat(),
              'status': 'RUNNING', 'checks': {}, 'core_version': '0.2.0', 'export_version': '0.3.0'}
    checks = report['checks']
    def run(command, log):
        result = subprocess.run([str(x) for x in command], cwd=ROOT, text=True, encoding='utf-8', errors='replace', capture_output=True)
        (evidence/log).write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f'Command failed; inspect build/export-validation/{log}')
        return result.stdout
    try:
        assert sha(CORE) == CORE_SHA, 'Frozen AAR changed'
        manifest = json.loads((ROOT/'qualification/production-source-sha256.json').read_text())
        for entry in manifest['files']:
            assert sha(ROOT/entry['path']) == entry['sha256'], 'Qualified production source changed: ' + entry['path']
        checks['qualified_core'] = {'status':'PASS', 'sha256':CORE_SHA, 'production_files_unchanged':len(manifest['files'])}
        assert not list(ROOT.glob('.github/workflows/*')), 'Unexpected workflow'
        checks['no_github_workflows'] = 'PASS'
        if not args.skip_build:
            command = [ROOT/('gradlew.bat' if os.name == 'nt' else 'gradlew'),
                ':encoder-export:testDebugUnitTest', ':encoder-export:assembleDebugAndroidTest',
                ':encoder-export:publishReleasePublicationToStagingRepository', ':sample-app:assembleRelease',
                ':sample-app:assembleReleaseAndroidTest', '-PuwdevLocalDeviceQa=true', '--console=plain']
            if args.offline:
                command.append('--offline')
            run(command, 'gradle.log')
        checks['build'] = 'EXISTING_OUTPUTS_ONLY' if args.skip_build else 'PASS'
        suites = [ET.parse(p).getroot() for p in (ROOT/'encoder-export/build/test-results/testDebugUnitTest').glob('TEST-*.xml')]
        assert suites and all(int(s.get('failures',0)) == 0 and int(s.get('errors',0)) == 0 and int(s.get('skipped',0)) == 0 for s in suites)
        checks['jvm_tests'] = {'status':'PASS','tests':sum(int(s.get('tests',0)) for s in suites)}
        export = ROOT/'encoder-export/build/outputs/aar/encoder-export-release.aar'
        sample = ROOT/'sample-app/build/outputs/apk/release/sample-app-release.apk'
        with zipfile.ZipFile(CORE) as core, zipfile.ZipFile(sample) as apk, zipfile.ZipFile(export) as facade:
            assert not any(n.endswith('.so') for n in facade.namelist()), 'Facade must not ship a second core'
            with zipfile.ZipFile(io.BytesIO(facade.read('classes.jar'))) as classes:
                assert 'META-INF/uwdev-mp3codec-export/LICENSE' in classes.namelist()
            for abi in ('arm64-v8a','armeabi-v7a','x86_64'):
                assert core.read(f'jni/{abi}/libuwdev_mp3codec.so') == apk.read(f'lib/{abi}/libuwdev_mp3codec.so')
        checks['packaging'] = {'status':'PASS','native_abis_unchanged':3,'export_aar_sha256':sha(export),'sample_release_sha256':sha(sample)}
        if args.android_serial:
            sdk = os.getenv('ANDROID_HOME') or os.getenv('ANDROID_SDK_ROOT')
            adb = str(Path(sdk)/'platform-tools'/('adb.exe' if os.name=='nt' else 'adb')) if sdk else shutil.which('adb')
            if not adb:
                raise RuntimeError('Set ANDROID_HOME or put adb on PATH')
            def device(*parts, log='adb.log'):
                return run([adb,'-s',args.android_serial,*parts], log)
            test_apk = ROOT/'encoder-export/build/outputs/apk/androidTest/debug/encoder-export-debug-androidTest.apk'
            device('install','-r','-t',test_apk,log='install-core-tests.log')
            out = device('shell','am','instrument','-w','-r','dev.unicornwhodev.mp3codec.export.test/androidx.test.runner.AndroidJUnitRunner',log='android-core-tests.log')
            assert 'OK (3 tests)' in out and 'FAILURES' not in out
            target = evidence/'device'
            target.mkdir(exist_ok=True)
            device('pull','/sdcard/Android/data/dev.unicornwhodev.mp3codec.export.test/files/export-validation/.',target,log='pull.log')
            compatibility = json.loads((target/'compatibility.json').read_text())
            assert compatibility['status'] == 'PASS' and len(compatibility['cases']) == 24
            for case in compatibility['cases']:
                stem = case['configuration']
                assert case['direct_sha256'] == case['pcm_sha256'] == case['wav_sha256']
                for route in ('direct','pcm','wav'):
                    assert sha(target/f'{stem}-{route}.mp3') == case['direct_sha256']
            checks['android_core_compatibility'] = {'status':'PASS','configurations':24,'mp3_files':72,'android_decode_to_eos':24}
            ffmpeg = shutil.which('ffmpeg')
            if ffmpeg:
                for path in target.glob('*.mp3'):
                    run([ffmpeg,'-v','error','-xerror','-i',path,'-f','null','-'], 'ffmpeg-last.log')
                checks['ffmpeg_decode_to_eos'] = {'status':'PASS','files':len(list(target.glob('*.mp3')))}
            else:
                checks['ffmpeg_decode_to_eos'] = 'NOT_RUN: ffmpeg unavailable'
            device('install','-r',sample,log='install-sample.log')
            sample_tests = ROOT/'sample-app/build/outputs/apk/androidTest/release/sample-app-release-androidTest.apk'
            device('install','-r','-t',sample_tests,log='install-sample-tests.log')
            out = device('shell','am','instrument','-w','-r','dev.unicornwhodev.mp3codec.sample.test/androidx.test.runner.AndroidJUnitRunner',log='android-sample-tests.log')
            assert 'OK (1 test)' in out and 'FAILURES' not in out
            device('pull','/sdcard/Android/data/dev.unicornwhodev.mp3codec.sample/files/export-ui-validation.json',evidence/'sample-ui.json',log='pull-sample.log')
            checks['release_r8_sample'] = json.loads((evidence/'sample-ui.json').read_text())
        else:
            checks['android_core_compatibility'] = 'NOT_RUN: no explicit Android target'
            checks['release_r8_sample'] = 'NOT_RUN: no explicit Android target'
        report['status'] = 'PASS' if args.android_serial else 'PASS_LOCAL_CHECKS_ANDROID_PENDING'
    except BaseException as failure:
        report['status'] = 'FAIL'
        report['failure'] = str(failure) or type(failure).__name__
        raise
    finally:
        (evidence/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
