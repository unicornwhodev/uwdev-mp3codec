// SPDX-License-Identifier: MIT
export const version: string;
export const coordinate: string;
export function getMavenRepositoryPath(): string;
export function getAarPath(): string;
export function verifyArtifacts(baseDirectory?: string): {status: 'PASS'; version: string; filesVerified: number};
