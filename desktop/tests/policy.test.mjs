import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const config = JSON.parse(await read('../src-tauri/tauri.conf.json'));
const capability = JSON.parse(await read('../src-tauri/capabilities/setup-local.json'));
const permission = await read('../src-tauri/permissions/read-only-cli.toml');
const adapter = await read('../web/host-adapter.js');
const html = await read('../web/index.html');
const rust = await read('../src-tauri/src/lib.rs');
const rustMain = await read('../src-tauri/src/main.rs');
const rustBuild = await read('../src-tauri/build.rs');
const platformRust = await read('../src-tauri/src/platform.rs');
const vendor = JSON.parse(await read('../src-tauri/binaries/vendor-manifest.json'));
const packageJson = JSON.parse(await read('../package.json'));
const parity = JSON.parse(await read('../src-tauri/setup-parity.json'));
const electronParity = JSON.parse(await read('./fixtures/electron-setup/setup-parity.json'));
const electronHtml = await read('./fixtures/electron-setup/index.html');
const electronCss = await read('./fixtures/electron-setup/setup.css');
const electronSetup = await read('./fixtures/electron-setup/setup.js');
const electronDash = await read('./fixtures/electron-setup/agent-dash.js');
const css = await read('../web/setup.css');
const setup = await read('../web/setup.js');
const dash = await read('../web/agent-dash.js');
const iconSource = await read('../src-tauri/icons/source.svg');
const cliRust = await read('../src-tauri/src/cli.rs');

test('bundles exactly one target-qualified logical sidecar', () => {
  assert.deepEqual(config.bundle.externalBin, ['binaries/omnideck-cli']);
  assert.equal(config.identifier, 'dev.omnideck.desktop');
  assert.equal(config.productName, 'omnideck');
  assert.equal(config.version, '0.1.0-alpha.11');
  assert.equal(config.bundle.targets, 'all');
  assert.deepEqual(config.bundle.icon, [
    'icons/32x32.png',
    'icons/128x128.png',
    'icons/128x128@2x.png',
    'icons/icon.icns',
    'icons/icon.ico',
  ]);
  assert.match(packageJson.scripts['build:windows'], /--bundles nsis/);
  assert.match(packageJson.scripts['build:macos'], /--bundles dmg/);
  assert.match(packageJson.scripts['build:linux'], /--bundles appimage deb rpm/);
});

test('bundles the blue signal icon with readable Linux package assets', async () => {
  assert.equal(config.build.beforeBundleCommand, 'node scripts/prepare-icon-assets.mjs');
  assert.equal(packageJson.scripts['prepare:icons'], 'node scripts/prepare-icon-assets.mjs');
  assert.match(iconSource, /fill="#2563eb"/);
  assert.match(iconSource, /fill="#3b82f6"/);
  assert.match(iconSource, /fill="#60a5fa"/);
  assert.doesNotMatch(iconSource, /#7c5cff|#37d5d1|#f4b860/i);

  if (process.platform !== 'win32') {
    for (const icon of config.bundle.icon) {
      const metadata = await stat(new URL(`../src-tauri/${icon}`, import.meta.url));
      assert.equal(metadata.mode & 0o044, 0o044, `${icon} must be readable from a system package`);
    }
  }
});

test('local capability contains no generic or remote authority', () => {
  assert.equal(capability.local, true);
  assert.equal('remote' in capability, false);
  assert.deepEqual(capability.windows, ['main']);
  assert.equal(capability.windows.includes('hosted-app'), false);
  assert.deepEqual(capability.permissions, ['read-only-cli']);
  assert.doesNotMatch(JSON.stringify(capability), /shell:|process:|fs:|updater:|dialog:|opener:|core:event/i);
});

test('permission exposes only the four typed lifecycle commands', () => {
  assert.match(permission, /commands\.allow = \["bootstrap", "begin_setup", "open_app", "run_action"\]/);
  assert.doesNotMatch(permission, /spawn|execute|shell|filesystem|process/i);
  assert.deepEqual([...adapter.matchAll(/run\('([^']+)'/g)].map((match) => match[1]), [
    'begin_setup',
    'open_app',
    'run_action',
    'bootstrap',
  ]);
  assert.doesNotMatch(rustBuild, /cli_version|runtime_status/);
});

test('Rust owns all CLI arguments and guards navigation plus command origin', () => {
  assert.match(cliRust, /Self::Version => &\["--version"\]/);
  assert.match(cliRust, /Self::RuntimeStatus => &\["--json", "runtime", "status"\]/);
  assert.match(cliRust, /Self::InstanceStatus =>/);
  assert.match(cliRust, /Self::StartInstance =>/);
  assert.match(cliRust, /platform::resource_name\(CONTAINER_NAME\)/);
  assert.match(rust, /"environment"\.into\(\),\s+"ensure"\.into\(\)/);
  assert.match(rust, /WebviewWindowBuilder::new\(app, "main"/);
  assert.match(rust, /\.on_navigation\(is_local_setup_url\)/);
  assert.match(rust, /"hosted-app"/);
  assert.match(rust, /is_hosted_app_url/);
  assert.match(rust, /fn authorize_local_setup\(window: &WebviewWindow\)/);
  assert.doesNotMatch(adapter, /plugin-shell|Command\.sidecar|executable|argv|workingDirectory/);
});

test('hosted container window starts inert, resolves an exact dynamic origin, and has no capability', () => {
  assert.deepEqual(config.app.windows, []);
  assert.match(rust, /WebviewUrl::App\("hosted-placeholder\.html"\.into\(\)\)/);
  assert.match(rust, /\.visible\(false\)/);
  assert.match(rust, /\.enable_clipboard_access\(\)/);
  assert.match(rust, /\.initialization_script\(HOSTED_SHORTCUTS_SCRIPT\)/);
  assert.match(rust, /event\.ctrlKey \|\| event\.metaKey/);
  assert.match(rust, /key === 'f5'/);
  assert.match(rust, /key === 'r'/);
  assert.match(rust, /\.on_new_window\(/);
  assert.match(rust, /HostedNavigation::OpenExternal/);
  assert.match(rust, /matches!\(url\.scheme\(\), "http" \| "https"\)/);
  assert.match(rust, /platform::open_url\(url\.as_str\(\)\)/);
  assert.equal(capability.windows.includes('hosted-app'), false);
  assert.doesNotMatch(rust, /const HOSTED_APP_PORT/);
  assert.match(rust, /url\.host_str\(\) == Some\("127\.0\.0\.1"\)/);
  assert.match(rust, /url\.port\(\) == expected_port/);
  assert.match(rust, /format!\("http:\/\/127\.0\.0\.1:\{port\}"\)/);
});

test('packaged UI bootstraps through the typed lifecycle bridge', () => {
  assert.match(adapter, /DOMContentLoaded/);
  assert.match(adapter, /run\('bootstrap'/);
  assert.match(adapter, /new \(core\(\)\.Channel\)\(\)/);
  assert.match(rust, /OMNIDECK_DESKTOP_SMOKE_FILE/);
  assert.match(rust, /"mutation": false/);
  assert.match(html, /connect-src ipc: http:\/\/ipc\.localhost/);
});

test('release builds are GUI applications and platform behavior is isolated', () => {
  assert.match(rustMain, /windows_subsystem = "windows"/);
  assert.match(rust, /mod platform;/);
  assert.doesNotMatch(rust, /rundll32|explorer\.exe|xdg-open|Library\/Application Support/);
  assert.match(platformRust, /target_os = "windows"/);
  assert.match(platformRust, /target_os = "macos"/);
  assert.match(platformRust, /target_os = "linux"/);
});

test('the latest CLI alpha is pinned with six target binaries and SBOMs', () => {
  assert.equal(vendor.repository, 'omnideck-dev/cli');
  assert.equal(vendor.tag, 'v0.11.0-alpha.2');
  assert.equal(vendor.version, 'v0.11.0-alpha.2');
  assert.equal(vendor.commit, '6ea721020691');
  assert.equal(
    vendor.downloadBaseUrl,
    'https://github.com/omnideck-dev/cli/releases/download/v0.11.0-alpha.2',
  );
  assert.deepEqual(vendor.targets.map(({ targetTriple }) => targetTriple).sort(), [
    'aarch64-apple-darwin',
    'aarch64-pc-windows-msvc',
    'aarch64-unknown-linux-gnu',
    'x86_64-apple-darwin',
    'x86_64-pc-windows-msvc',
    'x86_64-unknown-linux-gnu',
  ]);
  assert.match(cliRust, /EXPECTED_CLI_VERSION: &str = "v0\.11\.0-alpha\.2"/);
  assert.match(cliRust, /EXPECTED_CLI_COMMIT: &str = "6ea721020691"/);
  assert.equal(packageJson.scripts['fetch:sidecars'], 'node scripts/fetch-sidecars.mjs');
  for (const command of Object.entries(packageJson.scripts)
    .filter(([name]) => name.startsWith('build:'))
    .map(([, command]) => command)) {
    assert.match(command, /fetch-sidecars\.mjs/);
  }
});

test('all setup copy, phases, and failure text exactly match Electron', () => {
  assert.deepEqual(parity, electronParity);
});

test('setup DOM, CSS, behavior, and visible text are byte-for-byte Electron parity', () => {
  assert.equal(css, electronCss);
  assert.equal(setup, electronSetup);
  assert.equal(dash, electronDash);
  const normalizedTauriHtml = html.replaceAll('\r\n', '\n')
    .replace('; connect-src ipc: http://ipc.localhost', '')
    .replace('    <script src="./host-adapter.js"></script>\n', '');
  assert.equal(normalizedTauriHtml, electronHtml.replaceAll('\r\n', '\n'));
});

test('setup progress and diagnostics stay in the primary surface', () => {
  assert.match(setup, /progressContext\.hidden = !hasStep/);
  assert.match(setup, /Step \$\{state\.step\} of \$\{state\.totalSteps\}/);
  assert.doesNotMatch(setup, /secondaryAction === 'show-logs'/);
  assert.match(setup, /technicalDetails\.open = false/);
  assert.match(setup, /state\.stage === 'preparing'/);
});
