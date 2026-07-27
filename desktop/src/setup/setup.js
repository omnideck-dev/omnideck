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
const doctorPanel = document.getElementById('doctor-panel');
const doctorResult = document.getElementById('doctor-result');
const diagnosticList = document.getElementById('diagnostic-list');
const technicalOutput = document.getElementById('technical-output');

let currentState = { stage: 'welcome' };

function renderDiagnostics(state) {
  const diagnostics = Array.isArray(state.diagnostics) ? state.diagnostics : [];
  doctorPanel.hidden = state.stage !== 'error' || diagnostics.length === 0;
  diagnosticList.replaceChildren();
  if (doctorPanel.hidden) return;

  doctorResult.textContent = state.diagnosticResult || 'Issue found';
  technicalOutput.textContent = state.technical || 'See the diagnostic log for more information.';
  diagnosticList.replaceChildren(...diagnostics.map((diagnostic) => {
    const row = document.createElement('div');
    row.className = 'diagnostic-row';
    row.dataset.status = diagnostic.status;

    const icon = document.createElement('span');
    icon.className = 'diagnostic-icon';
    icon.textContent = diagnostic.status === 'pass'
      ? '✓'
      : diagnostic.status === 'issue'
        ? '!'
        : '–';
    const label = document.createElement('span');
    label.textContent = diagnostic.label;
    const value = document.createElement('span');
    value.className = 'diagnostic-value';
    value.textContent = diagnostic.value;
    row.append(icon, label, value);
    return row;
  }));
}

function render(state) {
  currentState = state;
  document.documentElement.dataset.stage = state.stage;
  title.textContent = state.title;
  detail.textContent = state.detail;
  eyebrow.textContent = state.stage === 'ready'
    ? 'READY'
    : state.stage === 'error'
      ? 'SETUP NEEDS ATTENTION'
      : state.stage === 'welcome'
        ? 'WELCOME'
        : state.setupReason === 'update'
          ? 'UPDATING'
          : state.setupReason === 'repair'
            ? 'PREPARING'
            : 'FIRST-TIME SETUP';

  primary.hidden = !(
    state.canStart
    || state.canRetry
    || state.canOpen
    || state.primaryAction
  );
  primary.textContent = state.primaryLabel || (
    state.canOpen
      ? 'Open omnideck'
      : state.canRetry
        ? 'Try again'
        : 'Set up omnideck'
  );
  primary.disabled = false;

  logs.hidden = state.stage !== 'error';
  renderDiagnostics(state);

  const hasProgress = Number.isFinite(state.progress);
  const hasIndeterminateProgress = Boolean(state.indeterminate);
  progressWrap.hidden = !(hasProgress || hasIndeterminateProgress);
  progressWrap.classList.toggle('is-indeterminate', hasIndeterminateProgress);
  progress.style.width = hasProgress ? `${Math.round(state.progress * 100)}%` : '';
  if (hasProgress) {
    progressTrack.setAttribute('aria-valuenow', String(Math.round(state.progress * 100)));
    progressTrack.removeAttribute('aria-valuetext');
  } else {
    progressTrack.removeAttribute('aria-valuenow');
    if (hasIndeterminateProgress) progressTrack.setAttribute('aria-valuetext', 'In progress');
    else progressTrack.removeAttribute('aria-valuetext');
  }
  spinner.hidden = progressWrap.hidden === false || ['welcome', 'error', 'ready'].includes(state.stage);
  footnote.hidden = ['error', 'ready'].includes(state.stage);
  window.agentDashSetupState?.(state);
}

primary.addEventListener('click', async () => {
  primary.disabled = true;
  if (currentState.primaryAction) {
    await window.omnideckDesktop.doctorAction(currentState.primaryAction);
  } else if (currentState.canOpen) {
    await window.omnideckDesktop.openApp();
  } else if (currentState.canRetry) {
    await window.omnideckDesktop.retry();
  } else {
    await window.omnideckDesktop.beginSetup();
  }
});

logs.addEventListener('click', () => window.omnideckDesktop.showLogs());
window.omnideckDesktop.onState(render);
