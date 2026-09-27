import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { compareVersions, nextVersion, requiredBump, planRelease, releaseBody, readRelease, verifyCi } from '../scripts/weekly-app-release.mjs';

function fixture(t) {
  const root = mkdtempSync(join(fileURLToPath(new URL('../', import.meta.url)), '.weekly-release-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  const write = (path, text) => { mkdirSync(join(root, path, '..'), { recursive: true }); writeFileSync(join(root, path), text); };
  const commit = message => { git('add', '.'); git('commit', '-qm', message); return git('rev-parse', 'HEAD'); };
  git('init', '-q', '-b', 'main'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.com');
  write('docs/releases/app-v0.3.0.md', '# omnideck app 0.3.0\n');
  write('server/app.py', 'original\n');
  commit('chore(release): prepare app 0.3.0');
  const fragment = (name, target = 'app', type = 'fixed', bump = '') => write(`release-notes.d/${name}.md`, `---\ntarget: ${target}\ntype: ${type}\narea: browser\n${bump ? `bump: ${bump}\n` : ''}---\n\nA reviewed change.\n`);
  const plan = (options = {}) => planRelease({ root, tags: ['0.2.9', 'latest', '0.3.0', 'main-abc1234', '0.4.0-beta.1'], ...options });
  return { root, git, write, commit, fragment, plan };
}

test('numeric semver, features, fixes, and pre-1.0 breaking policy', () => {
  assert.ok(compareVersions('0.10.0', '0.9.9') > 0);
  assert.equal(nextVersion('0.3.9', 'patch'), '0.3.10');
  assert.equal(nextVersion('0.3.9', 'minor'), '0.4.0');
  assert.equal(nextVersion('0.3.9', 'major'), '0.4.0');
  assert.equal(nextVersion('0.3.9', 'major', 'major'), '1.0.0');
  assert.equal(nextVersion('1.3.9', 'major'), '2.0.0');
  assert.throws(() => compareVersions('01.0.0', '1.0.0'));
  assert.equal(requiredBump([{ type: 'fixed' }], []), 'patch');
  assert.equal(requiredBump([{ type: 'added' }], []), 'minor');
  assert.equal(requiredBump([{ type: 'changed', bump: 'major' }], []), 'major');
  assert.equal(requiredBump([], ['feat(api)!: remove endpoint']), 'major');
  assert.equal(requiredBump([], ['fix(api): change\n\nBREAKING CHANGE: changed contract']), 'major');
});

test('empty, desktop-only, and documentation changes skip app publication', t => {
  const f = fixture(t);
  assert.equal(f.plan().skip, true);
  f.fragment('desktop', 'desktop', 'added'); f.write('desktop/app.rs', 'new'); f.write('docs/readme.md', 'new');
  f.commit('feat(desktop)!: change host');
  assert.equal(f.plan().skip, true);
});

test('mixed targets include only new app fragments and leave the checkout untouched', t => {
  const f = fixture(t);
  f.fragment('desktop', 'desktop', 'added', 'major'); f.write('desktop/app.rs', 'new'); f.commit('feat(desktop)!: change host');
  f.fragment('app'); f.write('server/app.py', 'fixed'); f.commit('fix(browser): correct state');
  const plan = f.plan();
  assert.equal(plan.version, '0.3.1');
  assert.deepEqual(plan.fragments, ['release-notes.d/app.md']);
  assert.ok(existsSync(join(f.root, 'release-notes.d/app.md')));
  assert.ok(existsSync(join(f.root, 'release-notes.d/desktop.md')));
  assert.equal(f.git('status', '--porcelain'), '');
  const release = published(f, plan);
  assert.equal(f.plan({ tags: ['0.3.1'], releases: [release] }).skip, true);
  f.fragment('next', 'app', 'added'); f.write('server/app.py', 'feature'); f.commit('feat: next');
  const next = f.plan({ tags: ['0.3.1'], releases: [release] });
  assert.equal(next.version, '0.4.0');
  assert.deepEqual(next.fragments, ['release-notes.d/next.md']);
});

const digest = 'sha256:' + 'a'.repeat(64);
function checkpoint(plan, draft = true) {
  return { id: 1, tag_name: `app-v${plan.version}`, body: releaseBody(plan, digest), draft, prerelease: false };
}
function published(f, plan) {
  f.git('tag', `app-v${plan.version}`, plan.source_sha);
  return checkpoint(plan, false);
}

test('unnoted maintenance, feature titles, and breaking changes select the appropriate version', t => {
  const f = fixture(t);
  f.write('server/app.py', 'refactor'); f.commit('refactor(runtime): simplify ownership');
  assert.equal(f.plan().version, '0.3.1');
  assert.match(f.plan().notes, /Internal application maintenance/);
  f.fragment('feature'); f.write('server/app.py', 'feature'); f.commit('feat(runtime): new capability');
  assert.equal(f.plan().version, '0.4.0');
  f.write('server/app.py', 'breaking'); f.commit('refactor(runtime)!: change interface');
  assert.equal(f.plan({ preOneBreaking: 'major' }).version, '1.0.0');
});

test('retry uses the draft source even after main advances or the image was pushed', t => {
  const f = fixture(t);
  f.fragment('first'); f.write('server/app.py', 'fix'); f.commit('fix: first');
  const plan = f.plan();
  const release = checkpoint(plan);
  f.fragment('later', 'app', 'added'); f.write('server/app.py', 'feature'); f.commit('feat: later');
  for (const tags of [['0.3.0'], ['0.3.0', '0.3.1']]) {
    const retry = f.plan({ tags, releases: [release] });
    assert.equal(retry.version, '0.3.1');
    assert.equal(retry.source_sha, plan.source_sha);
    assert.equal(retry.source_digest, digest);
    assert.equal(retry.notes, plan.notes);
  }
  const next = f.plan({ tags: ['0.3.1'], releases: [published(f, plan)] });
  assert.equal(next.version, '0.4.0');
  assert.deepEqual(next.fragments, ['release-notes.d/later.md']);
});

test('manual override cannot undercut the required bump or abandon a pending release', t => {
  const f = fixture(t);
  f.fragment('feature', 'app', 'added'); f.commit('feat: first');
  const plan = f.plan();
  assert.throws(() => f.plan({ manualVersion: '0.3.1' }), /at least/);
  assert.throws(() => f.plan({ manualVersion: 'v1.0.0' }), /plain/);
  assert.equal(f.plan({ manualVersion: '1.0.0' }).version, '1.0.0');
  assert.throws(() => f.plan({ releases: [checkpoint(plan)], manualVersion: '1.0.0' }), /pending/);
  const release = published(f, plan);
  const retry = f.plan({ tags: [plan.version], releases: [release], manualVersion: plan.version });
  assert.equal(retry.source_sha, plan.source_sha);
});

test('CI verification requires latest exact-source main push success', () => {
  const success = { id: 1, head_sha: 'abc', head_branch: 'main', event: 'push', status: 'completed', conclusion: 'success' };
  verifyCi([success], 'abc');
  assert.throws(() => verifyCi([success], 'other'));
  assert.throws(() => verifyCi([{ ...success, event: 'pull_request' }], 'abc'));
  assert.throws(() => verifyCi([success, { ...success, id: 2, conclusion: 'failure' }], 'abc'));
  assert.throws(() => verifyCi([{ ...success, status: 'in_progress', conclusion: null }], 'abc'));
});

test('a lower explicit bump cannot downgrade an added or removed change', () => {
  assert.equal(requiredBump([{ type: 'added', bump: 'patch' }], []), 'minor');
  assert.equal(requiredBump([{ type: 'removed', bump: 'minor' }], []), 'major');
});

test('ambiguous or inconsistent release records fail closed', t => {
  const f = fixture(t);
  f.fragment('fix'); f.commit('fix: change');
  const plan = f.plan();
  const first = checkpoint(plan);
  const second = checkpoint({ ...plan, version: '0.3.2' });
  assert.throws(() => f.plan({ releases: [first, second] }), /Multiple pending/);
  assert.throws(() => f.plan({ releases: [first, first] }), /Duplicate/);
  assert.throws(() => f.plan({ releases: [{ ...first, body: 'missing record' }] }), /Missing/);
  assert.throws(() => f.plan({ releases: [checkpoint({ ...plan, notes: 'wrong notes' })] }), /committed source/);
  assert.throws(() => f.plan({ tags: ['0.3.0', '0.3.2'], releases: [first] }), /baseline/);
  assert.throws(() => f.plan({ tags: ['0.5.1'] }), /no app release record/);
  assert.throws(() => f.plan({ releases: [checkpoint(plan, false)] }), /no corresponding container/);
  assert.throws(() => f.plan({ tags: ['0.3.1'], releases: [checkpoint(plan, false)] }), /Missing published app tag/);
  f.git('tag', 'app-v0.3.1', plan.baseline_sha);
  assert.throws(() => f.plan({ tags: ['0.3.1'], releases: [checkpoint(plan, false)] }), /wrong source/);
});

test('released fragments cannot be changed or deleted, while unreleased drafts can be edited', t => {
  const f = fixture(t);
  f.fragment('released'); f.commit('fix: first');
  f.fragment('released', 'app', 'security'); f.commit('fix: revise before shipping');
  const plan = f.plan();
  const release = published(f, plan);
  f.fragment('released'); f.commit('fix: rewrite published history');
  assert.throws(() => f.plan({ tags: ['0.3.1'], releases: [release] }), /Published app fragment changed/);
  f.git('rm', 'release-notes.d/released.md'); f.commit('chore: delete history');
  assert.throws(() => f.plan({ tags: ['0.3.1'], releases: [release] }), /Published app fragment changed/);
});

test('breaking commits on a merged branch are included even with a plain merge title', t => {
  const f = fixture(t);
  f.git('checkout', '-qb', 'feature');
  f.write('server/app.py', 'breaking'); f.fragment('breaking'); f.commit('fix(api)!: change contract');
  f.git('checkout', '-q', 'main'); f.git('merge', '--no-ff', '-qm', 'Merge feature branch', 'feature');
  assert.equal(f.plan({ preOneBreaking: 'major' }).version, '1.0.0');
});

test('desktop releases are excluded, and app metadata round-trips through the release body', t => {
  const f = fixture(t);
  f.fragment('first'); f.commit('fix: first');
  const plan = f.plan({ releases: [{ tag_name: 'v1.0.0', body: 'desktop' }] });
  const parsed = readRelease(checkpoint(plan));
  assert.equal(parsed.source_sha, plan.source_sha);
  assert.equal(parsed.notes, plan.notes);
  assert.equal(parsed.source_digest, digest);
});
