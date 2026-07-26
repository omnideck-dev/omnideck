const title = document.getElementById('title');
const detail = document.getElementById('detail');
const eyebrow = document.getElementById('eyebrow');
const primary = document.getElementById('primary');
const logs = document.getElementById('logs');
const spinner = document.getElementById('spinner');
const progressWrap = document.getElementById('progress-wrap');
const progressTrack = progressWrap.querySelector('[role="progressbar"]');
const progress = document.getElementById('progress');
const footnote = document.getElementById('footnote');

let currentState = { stage: 'checking' };

function render(state) {
  currentState = state;
  document.documentElement.dataset.stage = state.stage;
  title.textContent = state.title;
  detail.textContent = state.detail;
  eyebrow.textContent = state.stage === 'ready'
    ? 'READY'
    : state.stage === 'error'
      ? 'SETUP NEEDS ATTENTION'
      : 'PRIVATE WORKSPACE';

  primary.hidden = !(state.canStart || state.canRetry || state.canOpen);
  primary.textContent = state.canOpen
    ? 'Open OmniDeck'
    : state.canRetry
      ? 'Try again'
      : 'Set up OmniDeck';
  primary.disabled = false;

  logs.hidden = state.stage !== 'error';
  spinner.hidden = ['welcome', 'error', 'ready'].includes(state.stage);
  progressWrap.hidden = state.progress == null;
  const percent = Math.round((state.progress || 0) * 100);
  progress.style.width = `${percent}%`;
  progressTrack.setAttribute('aria-valuenow', String(percent));
  footnote.hidden = ['error', 'ready'].includes(state.stage);
  window.agentDashSetupState?.(state);
}

primary.addEventListener('click', async () => {
  primary.disabled = true;
  if (currentState.canOpen) {
    await window.omnideckDesktop.openApp();
  } else if (currentState.canRetry) {
    await window.omnideckDesktop.retry();
  } else {
    await window.omnideckDesktop.beginSetup();
  }
});

logs.addEventListener('click', () => window.omnideckDesktop.showLogs());
window.omnideckDesktop.onState(render);
