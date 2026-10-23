// SPDX-License-Identifier: MIT
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const version = require('../package.json').version;
// Distribution and facade versions evolve independently of the frozen native core.
const coreVersion = '0.2.0';
const exportVersion = '0.3.0';
const coordinate = `io.github.unicornwhodev:uwdev-mp3codec:${coreVersion}`;
const coreCoordinate = coordinate;
const exportCoordinate = `io.github.unicornwhodev:uwdev-mp3codec-export:${exportVersion}`;
const getMavenRepositoryPath = () => path.join(root, 'maven');
const getAarPath = () => path.join(getMavenRepositoryPath(), 'io', 'github', 'unicornwhodev', 'uwdev-mp3codec', coreVersion, `uwdev-mp3codec-${coreVersion}.aar`);
const getExportAarPath = () => path.join(getMavenRepositoryPath(), 'io', 'github', 'unicornwhodev', 'uwdev-mp3codec-export', exportVersion, `uwdev-mp3codec-export-${exportVersion}.aar`);
const getDemoApkPath = () => path.join(root, 'demo', 'uwdev-mp3codec-demo.apk');
const getExampleProjectPath = () => path.join(root, 'example', 'android');

function verifyArtifacts(baseDirectory = root) {
  const base = path.resolve(baseDirectory);
  const manifest = JSON.parse(fs.readFileSync(path.join(base, 'INTEGRITY.json'), 'utf8'));
  if (manifest.version !== version || !Array.isArray(manifest.files) || manifest.files.length === 0) {
    throw new Error('Invalid artifact manifest');
  }
  for (const entry of manifest.files) {
    const file = path.resolve(base, entry.path);
    const relative = path.relative(base, file);
    if (path.isAbsolute(relative) || relative === '..' || relative.startsWith(`..${path.sep}`)) {
      throw new Error('Unsafe artifact manifest path');
    }
    const bytes = fs.readFileSync(file);
    if (crypto.createHash('sha256').update(bytes).digest('hex') !== entry.sha256) {
      throw new Error(`SHA-256 mismatch: ${entry.path}`);
    }
  }
  return {status: 'PASS', version, filesVerified: manifest.files.length};
}

module.exports = Object.freeze({version, coreVersion, exportVersion, coordinate, coreCoordinate, exportCoordinate,
  getMavenRepositoryPath, getAarPath, getExportAarPath, getDemoApkPath, getExampleProjectPath, verifyArtifacts});
