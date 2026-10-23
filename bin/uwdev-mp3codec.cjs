#!/usr/bin/env node
// SPDX-License-Identifier: MIT
'use strict';
const codec = require('../lib/index.cjs');
const command = process.argv[2] || 'info';
try {
  if (command === 'maven-path') console.log(codec.getMavenRepositoryPath());
  else if (command === 'aar-path') console.log(codec.getAarPath());
  else if (command === 'export-aar-path') console.log(codec.getExportAarPath());
  else if (command === 'demo-path') console.log(codec.getDemoApkPath());
  else if (command === 'example-path') console.log(codec.getExampleProjectPath());
  else if (command === 'verify') console.log(JSON.stringify(codec.verifyArtifacts(), null, 2));
  else if (command === 'info') console.log(JSON.stringify({version: codec.version, coreVersion: codec.coreVersion,
    exportVersion: codec.exportVersion, coordinate: codec.coordinate, exportCoordinate: codec.exportCoordinate,
    mavenRepository: codec.getMavenRepositoryPath(), aar: codec.getAarPath(), exportAar: codec.getExportAarPath(),
    demoApk: codec.getDemoApkPath(), exampleProject: codec.getExampleProjectPath(),
    encodingRuntime: 'Android Kotlin/JNI', nodeEncodingApi: false}, null, 2));
  else throw new Error('Usage: uwdev-mp3codec [info|verify|maven-path|aar-path|export-aar-path|demo-path|example-path]');
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
