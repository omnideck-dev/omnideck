import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { verifyRuntimeDependencies } from '../scripts/verify-windows-runtime.mjs';

test('static runtime permits Windows system DLLs, including the OS-provided universal CRT', () => {
  assert.deepEqual(verifyRuntimeDependencies(`
    Image has the following dependencies:
      KERNEL32.dll
      api-ms-win-crt-runtime-l1-1-0.dll
  `), ['KERNEL32.dll', 'api-ms-win-crt-runtime-l1-1-0.dll']);
});

test('rejects the VC++ imports that made the packaged host fail before startup', () => {
  for (const dependency of ['VCRUNTIME140.dll', 'VCRUNTIME140_1.dll', 'msvcp140.dll', 'CONCRT140.dll']) {
    assert.throws(() => verifyRuntimeDependencies(`    KERNEL32.dll\n    ${dependency}\n`),
      /must statically link/);
  }
});

test('an empty or unexpected dumpbin response cannot count as a pass', () => {
  for (const output of ['', 'fatal error LNK1104: cannot open file']) {
    assert.throws(() => verifyRuntimeDependencies(output), /did not report/);
  }
});

test('Windows builds enforce static runtime and inspect the produced host before upload', async () => {
  const read = (file) => readFile(new URL(file, import.meta.url), 'utf8');
  const build = await read('../src-tauri/build.rs');
  const workflow = await read('../../.github/workflows/desktop.yml');
  assert.match(build, /set_var\("STATIC_VCRUNTIME", "true"\)/);
  assert(build.indexOf('set_var(') < build.indexOf('tauri_build::build()'));
  assert.match(workflow, /if: runner\.os == 'Windows'[\s\S]*?node scripts\/verify-windows-runtime\.mjs src-tauri\/target\/\$\{\{ matrix.target \}\}\/release\/omnideck-desktop\.exe/);
  assert(workflow.indexOf('node scripts/verify-windows-runtime.mjs') < workflow.indexOf('name: Upload native installers'));
});
