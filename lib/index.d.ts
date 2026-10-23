// SPDX-License-Identifier: MIT
export const version: string;
export const coreVersion: string;
export const exportVersion: string;
/** Backward-compatible alias for coreCoordinate. */
export const coordinate: string;
export const coreCoordinate: string;
export const exportCoordinate: string;
export function getMavenRepositoryPath(): string;
/** The unchanged qualified 0.2.0 core AAR. */
export function getAarPath(): string;
export function getExportAarPath(): string;
export function getDemoApkPath(): string;
export function getExampleProjectPath(): string;
export function verifyArtifacts(baseDirectory?: string): {status: 'PASS'; version: string; filesVerified: number};
