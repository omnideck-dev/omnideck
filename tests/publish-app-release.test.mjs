import assert from 'node:assert/strict';
import test from 'node:test';
import { publishRelease } from '../.github/scripts/publish-app-release.mjs';
import { readRelease } from '../scripts/weekly-app-release.mjs';

const digest = 'sha256:' + 'a'.repeat(64);
const plan = {
  version: '0.5.1', previous: '0.5.0', baseline_sha: 'b'.repeat(40),
  source_sha: 'c'.repeat(40), bump: 'patch', fragments: ['release-notes.d/fix.md'],
  notes: '# omnideck app 0.5.1\n\n## Fixed\n\n- A change.\n',
};
function fixture() {
  const state = { release: null, target: null, digest: null, calls: [], fail: '' };
  const mutate = name => {
    state.calls.push(name);
    if (state.fail === name) throw new Error(`Simulated ${name} failure`);
  };
  const adapter = {
    findRelease() { return state.release; },
    tagTarget() { return state.target; },
    imageDigest() {
      if (state.fail === 'registry-read') throw new Error('registry authentication failure');
      return state.digest;
    },
    createDraft(data) {
      mutate('draft');
      assert.equal(data.make_latest, 'false');
      assert.equal(data.target_commitish, plan.source_sha);
      state.release = { id: 7, html_url: 'https://example.test/release', ...data };
      return state.release;
    },
    promoteImage(version, selectedDigest) {
      mutate('promote');
      assert.equal(version, plan.version);
      assert.equal(state.release.draft, true);
      assert.equal(readRelease(state.release).source_digest, selectedDigest);
      state.digest = selectedDigest;
    },
    publishDraft(id) {
      mutate('publish');
      assert.equal(id, state.release.id);
      assert.equal(state.digest, digest);
      state.target = plan.source_sha;
      state.release = { ...state.release, draft: false };
      return state.release;
    },
  };
  const publish = (options = {}) => publishRelease({ plan, digest, adapter, ...options });
  return { state, adapter, publish };
}

test('dry run does not create records, tags, or images', () => {
  const f = fixture();
  assert.equal(f.publish({ dryRun: true }).dryRun, true);
  assert.deepEqual(f.state.calls, []);
});

test('record precedes image publication and completed runs are idempotent', () => {
  const f = fixture();
  assert.equal(f.publish().url, 'https://example.test/release');
  assert.deepEqual(f.state.calls, ['draft', 'promote', 'publish']);
  f.publish();
  assert.deepEqual(f.state.calls, ['draft', 'promote', 'publish']);
});

for (const failure of ['draft', 'promote', 'publish']) {
  test(`retry recovers after ${failure} fails without replacing the reserved release`, () => {
    const f = fixture();
    f.state.fail = failure;
    assert.throws(() => f.publish(), /Simulated/);
    const draftId = f.state.release?.id;
    const resumedPlan = f.state.release ? readRelease(f.state.release) : plan;
    f.state.fail = '';
    f.publish({ plan: resumedPlan });
    assert.equal(f.state.release.draft, false);
    if (draftId) assert.equal(f.state.release.id, draftId);
    if (failure === 'publish') assert.equal(f.state.calls.filter(c => c === 'promote').length, 1);
  });
}

test('registry read failures do not reserve or publish a release', () => {
  const f = fixture();
  f.state.fail = 'registry-read';
  assert.throws(() => f.publish(), /authentication/);
  assert.deepEqual(f.state.calls, []);
});

test('a reserved source, existing version, or existing tag cannot be overwritten', () => {
  const f = fixture();
  f.state.fail = 'promote';
  assert.throws(() => f.publish());
  f.state.fail = '';
  const resumed = readRelease(f.state.release);
  assert.throws(() => f.publish({ plan: resumed, digest: 'sha256:' + 'd'.repeat(64) }), /digest changed/);
  assert.throws(() => f.publish({ plan: { ...plan, notes: 'different' } }), /differs/);
  f.state.release.target_commitish = 'd'.repeat(40);
  assert.throws(() => f.publish(), /differs/);
  f.state.release.target_commitish = plan.source_sha;
  f.state.target = 'd'.repeat(40);
  assert.throws(() => f.publish(), /different source/);
  f.state.target = null;
  f.state.digest = 'sha256:' + 'd'.repeat(64);
  assert.throws(() => f.publish(), /different digest/);
  f.state.digest = digest;
  f.state.release = null;
  assert.throws(() => f.publish(), /without its release checkpoint/);
  assert.throws(() => f.publish({ plan: resumed }), /disappeared/);
});

test('a published record missing its image or tag requires investigation', () => {
  const f = fixture();
  f.publish();
  f.state.target = null;
  assert.throws(() => f.publish(), /tag is missing/);
  f.state.target = plan.source_sha;
  f.state.digest = null;
  assert.throws(() => f.publish(), /image is missing/);
});
