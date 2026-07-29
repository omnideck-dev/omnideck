(function exposeAgentDash(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.AgentDash = api;
  }
}(typeof globalThis === 'object' ? globalThis : this, () => {
  'use strict';

  const WIDTH = 720;
  const HEIGHT = 360;
  const GROUND_Y = 302;
  const PLAYER_X = 94;
  const PLAYER_WIDTH = 42;
  const PLAYER_HEIGHT = 50;
  const GRAVITY = 1_650;
  const JUMP_VELOCITY = -650;

  function initialState() {
    return {
      mode: 'idle',
      elapsed: 0,
      distance: 0,
      bonus: 0,
      speed: 235,
      spawnIn: 1.15,
      player: {
        x: PLAYER_X,
        y: GROUND_Y - PLAYER_HEIGHT,
        width: PLAYER_WIDTH,
        height: PLAYER_HEIGHT,
        velocityY: 0,
      },
      objects: [],
      particles: [],
    };
  }

  function start(state) {
    const next = initialState();
    Object.assign(state, next, { mode: 'running' });
    return state;
  }

  function score(state) {
    return Math.floor(state.distance / 10) + state.bonus;
  }

  function jump(state) {
    if (state.mode === 'idle' || state.mode === 'over') {
      start(state);
    }
    if (state.mode !== 'running') return false;
    const floor = GROUND_Y - state.player.height;
    if (state.player.y < floor - 2) return false;
    state.player.velocityY = JUMP_VELOCITY;
    return true;
  }

  function overlaps(a, b, padding = 0) {
    return (
      a.x + padding < b.x + b.width
      && a.x + a.width - padding > b.x
      && a.y + padding < b.y + b.height
      && a.y + a.height - padding > b.y
    );
  }

  function addBurst(state, x, y, color, count = 8) {
    for (let index = 0; index < count; index += 1) {
      const angle = (Math.PI * 2 * index) / count;
      state.particles.push({
        x,
        y,
        velocityX: Math.cos(angle) * (45 + (index % 3) * 16),
        velocityY: Math.sin(angle) * (45 + (index % 2) * 18),
        life: 0.55,
        color,
      });
    }
  }

  function spawnObject(state, random) {
    const obstacleHeight = 38 + Math.floor(random() * 35);
    const obstacleWidth = 32 + Math.floor(random() * 29);
    state.objects.push({
      kind: 'obstacle',
      x: WIDTH + 30,
      y: GROUND_Y - obstacleHeight,
      width: obstacleWidth,
      height: obstacleHeight,
      variant: Math.floor(random() * 3),
    });

    if (random() > 0.28) {
      const cardHeight = 30;
      state.objects.push({
        kind: 'card',
        x: WIDTH + 43 + obstacleWidth * 0.35,
        y: Math.max(112, GROUND_Y - obstacleHeight - 72 - random() * 42),
        width: 22,
        height: cardHeight,
        phase: random() * Math.PI * 2,
      });
    }

    const difficulty = Math.min(0.42, state.elapsed / 95);
    state.spawnIn = 1.16 + random() * 0.72 - difficulty;
  }

  function step(state, elapsedSeconds, random = Math.random) {
    if (state.mode !== 'running') return state;
    const delta = Math.max(0, Math.min(0.04, elapsedSeconds));
    state.elapsed += delta;
    state.speed = Math.min(420, 235 + state.elapsed * 3.1);
    state.distance += state.speed * delta;

    state.player.velocityY += GRAVITY * delta;
    state.player.y += state.player.velocityY * delta;
    const floor = GROUND_Y - state.player.height;
    if (state.player.y >= floor) {
      state.player.y = floor;
      state.player.velocityY = 0;
    }

    state.spawnIn -= delta;
    if (state.spawnIn <= 0) spawnObject(state, random);

    for (const object of state.objects) {
      object.x -= state.speed * delta;
      if (object.kind === 'card') {
        object.y += Math.sin(state.elapsed * 5 + object.phase) * 0.17;
      }
    }

    for (const particle of state.particles) {
      particle.life -= delta;
      particle.x += particle.velocityX * delta;
      particle.y += particle.velocityY * delta;
      particle.velocityY += 180 * delta;
    }
    state.particles = state.particles.filter((particle) => particle.life > 0);

    const playerHitbox = {
      x: state.player.x + 4,
      y: state.player.y + 3,
      width: state.player.width - 8,
      height: state.player.height - 4,
    };
    for (const object of state.objects) {
      if (object.collected || !overlaps(playerHitbox, object, object.kind === 'obstacle' ? 4 : 0)) {
        continue;
      }
      if (object.kind === 'card') {
        object.collected = true;
        state.bonus += 50;
        addBurst(state, object.x + object.width / 2, object.y + object.height / 2, '#60a5fa');
      } else {
        state.mode = 'over';
        addBurst(
          state,
          state.player.x + state.player.width,
          state.player.y + state.player.height / 2,
          '#fb7185',
          12,
        );
        break;
      }
    }

    state.objects = state.objects.filter((object) => object.x + object.width > -30 && !object.collected);
    return state;
  }

  return {
    GROUND_Y,
    HEIGHT,
    WIDTH,
    initialState,
    jump,
    overlaps,
    score,
    start,
    step,
  };
}));

(function runAgentDash() {
  'use strict';

  if (typeof document !== 'object' || !globalThis.AgentDash) return;

  const game = globalThis.AgentDash;
  const canvas = document.getElementById('agent-dash');
  const context = canvas.getContext('2d');
  const overlay = document.getElementById('game-overlay');
  const message = document.getElementById('game-message');
  const hint = document.getElementById('game-hint');
  const scoreNode = document.getElementById('score');
  const bestNode = document.getElementById('best');
  const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const stars = Array.from({ length: 42 }, (_, index) => ({
    x: (index * 97) % game.WIDTH,
    y: 24 + ((index * 53) % 190),
    radius: index % 7 === 0 ? 1.4 : 0.75,
    depth: 0.18 + (index % 5) * 0.06,
  }));

  let state = game.initialState();
  let setupStarted = false;
  let frameHandle = null;
  let lastFrame = performance.now();
  let best = Number.parseInt(localStorage.getItem('omnideck-agent-dash-best') || '0', 10) || 0;
  let lastRenderedScore = -1;
  bestNode.textContent = String(best).padStart(4, '0');

  function roundedRect(x, y, width, height, radius) {
    const bounded = Math.min(radius, width / 2, height / 2);
    context.beginPath();
    context.moveTo(x + bounded, y);
    context.arcTo(x + width, y, x + width, y + height, bounded);
    context.arcTo(x + width, y + height, x, y + height, bounded);
    context.arcTo(x, y + height, x, y, bounded);
    context.arcTo(x, y, x + width, y, bounded);
    context.closePath();
  }

  // The sky never changes, so the gradient is built once instead of per frame.
  const skyGradient = context.createLinearGradient(0, 0, 0, game.HEIGHT);
  skyGradient.addColorStop(0, '#0a1020');
  skyGradient.addColorStop(0.62, '#10182a');
  skyGradient.addColorStop(1, '#10131c');

  function drawBackground() {
    context.fillStyle = skyGradient;
    context.fillRect(0, 0, game.WIDTH, game.HEIGHT);

    for (const star of stars) {
      const shift = reducedMotion ? 0 : (state.distance * star.depth) % (game.WIDTH + 20);
      const x = (star.x - shift + game.WIDTH + 20) % (game.WIDTH + 20);
      context.globalAlpha = 0.33 + star.depth;
      context.fillStyle = '#b9d5ff';
      context.beginPath();
      context.arc(x, star.y, star.radius, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = 1;

    const skylineShift = reducedMotion ? 0 : (state.distance * 0.12) % 98;
    context.fillStyle = '#111b31';
    for (let index = -2; index < 10; index += 1) {
      const x = index * 98 - skylineShift;
      const height = 35 + ((index + 12) % 4) * 13;
      context.fillRect(x, game.GROUND_Y - height, 64, height);
      context.fillRect(x + 70, game.GROUND_Y - height * 0.7, 23, height * 0.7);
    }

    context.strokeStyle = 'rgba(96, 165, 250, 0.12)';
    context.lineWidth = 1;
    for (let y = game.GROUND_Y + 14; y < game.HEIGHT; y += 14) {
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(game.WIDTH, y);
      context.stroke();
    }
    const gridShift = reducedMotion ? 0 : state.distance % 60;
    for (let x = -gridShift; x < game.WIDTH + 60; x += 60) {
      context.beginPath();
      context.moveTo(x, game.GROUND_Y);
      context.lineTo(x - 24, game.HEIGHT);
      context.stroke();
    }

    context.strokeStyle = '#2d4264';
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(0, game.GROUND_Y + 0.5);
    context.lineTo(game.WIDTH, game.GROUND_Y + 0.5);
    context.stroke();
  }

  function drawAgent() {
    const { x, y, width, height } = state.player;
    context.save();
    context.shadowColor = 'rgba(59, 130, 246, 0.7)';
    context.shadowBlur = 18;
    const body = context.createLinearGradient(x, y, x + width, y + height);
    body.addColorStop(0, '#60a5fa');
    body.addColorStop(1, '#2563eb');
    context.fillStyle = body;
    roundedRect(x, y + 7, width, height - 7, 11);
    context.fill();
    context.restore();

    context.strokeStyle = '#93c5fd';
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(x + width / 2, y + 7);
    context.lineTo(x + width / 2, y + 1);
    context.stroke();
    context.fillStyle = '#c4ddff';
    context.beginPath();
    context.arc(x + width / 2, y + 1, 2.5, 0, Math.PI * 2);
    context.fill();

    context.fillStyle = '#07111f';
    roundedRect(x + 7, y + 17, width - 14, 16, 6);
    context.fill();
    context.fillStyle = '#dbeafe';
    context.fillRect(x + 13, y + 23, 4, 4);
    context.fillRect(x + width - 17, y + 23, 4, 4);

    const footOffset = Math.abs(state.player.velocityY) > 1
      ? 0
      : Math.sin(state.elapsed * 18) * 3;
    context.strokeStyle = '#93c5fd';
    context.lineWidth = 4;
    context.lineCap = 'round';
    context.beginPath();
    context.moveTo(x + 12, y + height - 2);
    context.lineTo(x + 9 + footOffset, y + height + 4);
    context.moveTo(x + width - 12, y + height - 2);
    context.lineTo(x + width - 9 - footOffset, y + height + 4);
    context.stroke();
  }

  function drawObstacle(object) {
    context.save();
    context.shadowColor = 'rgba(251, 113, 133, 0.25)';
    context.shadowBlur = 10;
    context.fillStyle = object.variant === 1 ? '#7c3aed' : object.variant === 2 ? '#c2410c' : '#be123c';
    roundedRect(object.x, object.y + 8, object.width, object.height - 8, 6);
    context.fill();
    context.restore();

    context.fillStyle = 'rgba(255, 255, 255, 0.18)';
    context.fillRect(object.x + 6, object.y + 16, Math.max(10, object.width - 12), 3);
    context.fillRect(object.x + 6, object.y + 23, Math.max(7, object.width * 0.55), 3);
    context.fillStyle = '#fb7185';
    roundedRect(object.x + object.width * 0.18, object.y, object.width * 0.64, 13, 4);
    context.fill();
  }

  function drawCard(object) {
    context.save();
    context.shadowColor = 'rgba(96, 165, 250, 0.9)';
    context.shadowBlur = 16;
    context.fillStyle = '#dbeafe';
    roundedRect(object.x, object.y, object.width, object.height, 5);
    context.fill();
    context.restore();
    context.fillStyle = '#2563eb';
    const bars = [8, 15, 11];
    for (let index = 0; index < bars.length; index += 1) {
      roundedRect(object.x + 5 + index * 4.5, object.y + object.height - 6 - bars[index], 3, bars[index], 2);
      context.fill();
    }
  }

  function drawParticles() {
    for (const particle of state.particles) {
      context.globalAlpha = Math.max(0, particle.life / 0.55);
      context.fillStyle = particle.color;
      context.beginPath();
      context.arc(particle.x, particle.y, 2.6, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = 1;
  }

  function draw() {
    drawBackground();
    for (const object of state.objects) {
      if (object.kind === 'card') drawCard(object);
      else drawObstacle(object);
    }
    drawAgent();
    drawParticles();
  }

  function showOverlay(title, help) {
    message.textContent = title;
    hint.textContent = help;
    overlay.hidden = false;
  }

  function hideOverlay() {
    overlay.hidden = true;
  }

  function saveBest() {
    const current = game.score(state);
    if (current <= best) return;
    best = current;
    localStorage.setItem('omnideck-agent-dash-best', String(best));
    bestNode.textContent = String(best).padStart(4, '0');
  }

  function handleAction() {
    if (!setupStarted) return;
    if (state.mode === 'over') {
      saveBest();
      game.start(state);
      hideOverlay();
      startLoop();
      return;
    }
    if (state.mode === 'idle') {
      game.start(state);
      hideOverlay();
    }
    game.jump(state);
    startLoop();
  }

  function updateOverlay() {
    if (!setupStarted) {
      showOverlay('Start setup to begin the run', 'Space / ↑ / click to jump');
      return;
    }
    if (state.mode === 'over') {
      showOverlay(`Run over — ${game.score(state)} points`, 'Press Space or click to run again');
      return;
    }
    hideOverlay();
  }

  canvas.addEventListener('pointerdown', () => {
    canvas.focus();
    handleAction();
  });
  document.addEventListener('keydown', (event) => {
    if (![' ', 'ArrowUp', 'w', 'W'].includes(event.key)) return;
    if (event.target instanceof HTMLButtonElement) return;
    event.preventDefault();
    handleAction();
  });

  globalThis.agentDashSetupState = (setupState) => {
    const workingStages = new Set([
      'installing',
      'downloading',
      'loading-image',
      'preparing',
      'starting',
      'finishing',
    ]);
    if (workingStages.has(setupState.stage) && !setupStarted) {
      setupStarted = true;
      game.start(state);
      startLoop();
    }
    updateOverlay();
  };

  function frame(now) {
    const delta = (now - lastFrame) / 1000;
    lastFrame = now;
    game.step(state, delta);
    const currentScore = game.score(state);
    if (currentScore !== lastRenderedScore) {
      scoreNode.textContent = String(currentScore).padStart(4, '0');
      lastRenderedScore = currentScore;
    }
    const stopped = state.mode !== 'running';
    if (stopped) {
      saveBest();
      updateOverlay();
    }
    draw();
    // Nothing moves unless a run is in progress, so the loop stops instead of
    // redrawing an identical frame sixty times a second while setup is
    // competing for the same thread.
    frameHandle = stopped ? null : requestAnimationFrame(frame);
  }

  function startLoop() {
    if (frameHandle !== null) return;
    lastFrame = performance.now();
    frameHandle = requestAnimationFrame(frame);
  }

  updateOverlay();
  draw();
}());
