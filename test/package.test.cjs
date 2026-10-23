// SPDX-License-Identifier: MIT
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const codec = require('../lib/index.cjs');
const root = path.resolve(__dirname, '..');

test('the public coordinate resolves to existing bundled Maven and AAR artifacts', () => {
  assert.equal(codec.coordinate, 'io.github.unicornwhodev:uwdev-mp3codec:0.2.0');
  assert.equal(codec.coreCoordinate, codec.coordinate);
  assert.equal(codec.version, '0.3.0');
  assert.equal(codec.exportCoordinate, 'io.github.unicornwhodev:uwdev-mp3codec-export:0.3.0');
  assert.ok(fs.statSync(codec.getAarPath()).isFile());
  assert.ok(fs.statSync(codec.getExportAarPath()).isFile());
  assert.ok(fs.statSync(codec.getDemoApkPath()).isFile());
  assert.ok(fs.statSync(path.join(codec.getExampleProjectPath(), 'gradlew.bat')).isFile());
  assert.ok(fs.readFileSync(path.join(codec.getExampleProjectPath(), 'app/build.gradle.kts'), 'utf8').includes(codec.exportCoordinate));
  assert.ok(fs.statSync(codec.getMavenRepositoryPath()).isDirectory());
  assert.equal(codec.verifyArtifacts().status, 'PASS');
});

test('the installed CLI returns useful Android integration paths and verifies the bundle', () => {
  const cli = path.join(root, 'bin/uwdev-mp3codec.cjs');
  const run = arg => execFileSync(process.execPath, [cli, arg], {encoding: 'utf8'}).trim();
  assert.equal(run('aar-path'), codec.getAarPath());
  assert.equal(run('maven-path'), codec.getMavenRepositoryPath());
  assert.equal(run('export-aar-path'), codec.getExportAarPath());
  assert.equal(run('demo-path'), codec.getDemoApkPath());
  assert.equal(run('example-path'), codec.getExampleProjectPath());
  assert.equal(JSON.parse(run('verify')).status, 'PASS');
  assert.equal(JSON.parse(run('info')).nodeEncodingApi, false);
  assert.throws(() => run('invalid-command'));
});

test('integrity verification rejects an altered Android binary', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'uwdev-codec-test-'));
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(root, 'INTEGRITY.json'), 'utf8'));
    for (const file of manifest.files) {
      const target = path.join(temporary, file.path);
      fs.mkdirSync(path.dirname(target), {recursive: true});
      fs.copyFileSync(path.join(root, file.path), target);
    }
    fs.copyFileSync(path.join(root, 'INTEGRITY.json'), path.join(temporary, 'INTEGRITY.json'));
    assert.equal(codec.verifyArtifacts(temporary).status, 'PASS');
    const binary = manifest.files.find(file => file.path.endsWith('.aar'));
    fs.appendFileSync(path.join(temporary, binary.path), Buffer.from([1]));
    assert.throws(() => codec.verifyArtifacts(temporary), /SHA-256 mismatch/);
  } finally {
    const relative = path.relative(path.resolve(os.tmpdir()), path.resolve(temporary));
    assert.ok(relative.startsWith('uwdev-codec-test-') && !relative.includes(path.sep));
    fs.rmSync(temporary, {recursive: true, force: true});
  }
});
