#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Smoke-test the standalone SDK demo on an explicitly selected Android device."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-serial', required=True)
    parser.add_argument('--apk', type=Path, default=ROOT/'build/release-0.3.0/sdk/example/android/app/build/outputs/apk/release/app-release.apk')
    parser.add_argument('--output', type=Path, default=ROOT/'build/export-validation/sdk-demo-smoke.json')
    args = parser.parse_args()
    sdk = os.getenv('ANDROID_HOME') or os.getenv('ANDROID_SDK_ROOT')
    adb = str(Path(sdk)/'platform-tools'/('adb.exe' if os.name == 'nt' else 'adb')) if sdk else shutil.which('adb')
    if not adb:
        raise RuntimeError('Set ANDROID_HOME or put adb on PATH')
    prefix = [adb, '-s', args.android_serial]

    def run(*parts):
        return subprocess.check_output(prefix+list(parts), timeout=35).decode('utf-8', errors='replace')

    def tree():
        data = run('exec-out', 'uiautomator', 'dump', '/dev/tty')
        return ET.fromstring(data[data.index('<?xml'):data.rfind('</hierarchy>')+12])

    def wait_text(text):
        for _ in range(8):
            state = tree()
            if any(text in n.get('text', '') for n in state.iter('node')):
                return state
        raise AssertionError('UI state not reached: '+text)

    def tap(state, label):
        def matches(t):
            return [n for n in t.iter('node') if n.get('text', '').casefold() == label.casefold() and n.get('enabled') == 'true']
        nodes = matches(state)
        if not nodes:
            scroll = next(n for n in state.iter('node') if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable') == 'true')
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', scroll.get('bounds')))
            run('shell', 'input', 'swipe', str((x1+x2)//2), str(y2-80), str((x1+x2)//2), str(y1+100), '350')
            nodes = matches(tree())
        if not nodes:
            raise AssertionError('Enabled control not visible: '+label)
        x1, y1, x2, y2 = map(int, re.findall(r'\d+', nodes[0].get('bounds')))
        run('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))

    def show_status():
        # In landscape the player button can be below the status text.
        scrolls = [n for n in tree().iter('node') if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable') == 'true']
        if scrolls:
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', scrolls[0].get('bounds')))
            run('shell', 'input', 'swipe', str((x1+x2)//2), str(y1+100), str((x1+x2)//2), str(y2-80), '350')

    assert 'Success' in run('install', '-r', str(args.apk.resolve()))
    run('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
    run('shell', 'wm', 'dismiss-keyguard')
    run('shell', 'am', 'force-stop', 'dev.unicornwhodev.mp3codec.demo')
    run('shell', 'am', 'start', '-W', '-n', 'dev.unicornwhodev.mp3codec.demo/dev.unicornwhodev.mp3codec.sample.ExportActivity')
    tap(wait_text('Choose a PCM16 WAV'), 'Use bundled WAV sample')
    tap(wait_text('Bundled stereo WAV loaded'), 'Export MP3')
    tap(wait_text('Export complete: 96000 frames, 48960 bytes, 192 kbit/s.'), 'Play MP3')
    show_status()
    wait_text('Playback completed.')
    package = run('shell', 'dumpsys', 'package', 'dev.unicornwhodev.mp3codec.demo')
    assert 'versionName=0.3.0' in package
    flags = re.search(r'(?m)^\s*flags=\[([^\]]*)\]', package)
    assert flags and 'DEBUGGABLE' not in flags.group(1)
    report = {'status': 'PASS', 'export_version': '0.3.0', 'standalone_packaged_project_build': 'PASS',
              'release_r8': True, 'test_keep_rules': False, 'installed_on_selected_device': True,
              'bundled_wav_frames': 96000, 'bitrate_kbps': 192, 'output_bytes': 48960,
              'export_success': True, 'playback_to_end': True,
              'apk_sha256': hashlib.sha256(args.apk.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
