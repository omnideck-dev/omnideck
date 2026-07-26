const assert = require('node:assert/strict');
const test = require('node:test');

const {
  GROUND_Y,
  initialState,
  jump,
  overlaps,
  score,
  start,
  step,
} = require('../src/setup/agent-dash.js');

test('Agent Dash starts and jumps from the ground', () => {
  const state = initialState();
  start(state);

  assert.equal(state.mode, 'running');
  assert.equal(jump(state), true);
  assert.ok(state.player.velocityY < 0);
  step(state, 0.02, () => 0.5);
  assert.ok(state.player.y < GROUND_Y - state.player.height);
});

test('Agent Dash prevents a second jump while airborne', () => {
  const state = initialState();
  start(state);
  jump(state);
  step(state, 0.02, () => 0.5);

  assert.equal(jump(state), false);
});

test('Agent Dash collects cards and awards a bonus', () => {
  const state = initialState();
  start(state);
  state.spawnIn = 100;
  state.objects.push({
    kind: 'card',
    x: state.player.x + 8,
    y: state.player.y + 8,
    width: 22,
    height: 30,
    phase: 0,
  });

  step(state, 0.01, () => 0.5);

  assert.equal(state.bonus, 50);
  assert.equal(state.objects.length, 0);
  assert.ok(score(state) >= 50);
});

test('Agent Dash ends a run when the agent meets an obstacle', () => {
  const state = initialState();
  start(state);
  state.spawnIn = 100;
  state.objects.push({
    kind: 'obstacle',
    x: state.player.x + 8,
    y: state.player.y + 4,
    width: 34,
    height: 46,
    variant: 0,
  });

  step(state, 0.01, () => 0.5);

  assert.equal(state.mode, 'over');
});

test('collision helper excludes separated rectangles', () => {
  assert.equal(
    overlaps(
      { x: 0, y: 0, width: 10, height: 10 },
      { x: 11, y: 0, width: 10, height: 10 },
    ),
    false,
  );
});
