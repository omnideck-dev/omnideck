import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export function verifyRuntimeDependencies(output) {
  const dependencies = [...output.matchAll(/^\s+([\w.-]+\.dll)\s*$/gim)]
    .map((match) => match[1]);
  assert(dependencies.length > 0, 'dumpbin did not report any DLL dependencies');
  const externalRuntime = dependencies.filter((name) => /^(?:vcruntime|msvcp|concrt)\d.*\.dll$/i.test(name));
  assert.equal(externalRuntime.length, 0,
    `Desktop must statically link the VC++ runtime; found ${externalRuntime.join(', ')}`);
  return dependencies;
}

function run(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.error?.message || result.stderr || `${command} failed`);
  return result.stdout;
}

export function main(args = process.argv.slice(2)) {
  assert.equal(process.platform, 'win32', 'Run this check on the native Windows build runner');
  assert.equal(args.length, 1, 'Usage: node scripts/verify-windows-runtime.mjs <desktop.exe>');
  const vswhere = path.join(process.env['ProgramFiles(x86)'],
    'Microsoft Visual Studio', 'Installer', 'vswhere.exe');
  const candidates = run(vswhere, ['-latest', '-products', '*', '-requires',
    'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-find',
    'VC/Tools/MSVC/*/bin/Hostx64/x64/dumpbin.exe']).trim().split(/\r?\n/).filter(Boolean);
  assert(candidates.length > 0, 'Visual Studio dumpbin was not found');
  // Host x64 dumpbin also reads ARM64 images; it never executes the target.
  const dependencies = verifyRuntimeDependencies(run(candidates.sort().at(-1),
    ['/nologo', '/dependents', path.resolve(args[0])]));
  console.log(`Verified static VC++ runtime (${dependencies.length} system DLL imports).`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main();
}
