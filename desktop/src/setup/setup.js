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
const actionError = document.getElementById('action-error');

let currentState = { stage: 'welcome' };

const DIAGNOSTIC_ICONS = { pass: '✓', issue: '!' };
const STAGE_EYEBROWS = {
  ready: 'READY',
  error: 'SETUP NEEDS ATTENTION',
  welcome: 'WELCOME',
};
const REASON_EYEBROWS = { update: 'UPDATING', repair: 'PREPARING' };

function eyebrowFor(state) {
  return STAGE_EYEBROWS[state.stage]
    || REASON_EYEBROWS[state.setupReason]
    || 'FIRST-TIME SETUP';
}

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
    icon.textContent = DIAGNOSTIC_ICONS[diagnostic.status] || '–';
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
  eyebrow.textContent = eyebrowFor(state);

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
  actionError.hidden = true;

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

function runAction() {
  if (currentState.primaryAction) {
    return window.omnideckDesktop.doctorAction(currentState.primaryAction);
  }
  if (currentState.canOpen) return window.omnideckDesktop.openApp();
  if (currentState.canRetry) return window.omnideckDesktop.retry();
  return window.omnideckDesktop.beginSetup();
}

// Re-enabling in a finally matters: the button is only otherwise re-enabled by
// the next state push, and a rejected action does not always produce one. That
// left the single control on the screen dead with nothing explaining why.
primary.addEventListener('click', async () => {
  primary.disabled = true;
  actionError.hidden = true;
  try {
    await runAction();
  } catch (error) {
    actionError.textContent = String(error?.message || error);
    actionError.hidden = false;
  } finally {
    primary.disabled = false;
  }
});

logs.addEventListener('click', async () => {
  try {
    await window.omnideckDesktop.showLogs();
  } catch (error) {
    actionError.textContent = String(error?.message || error);
    actionError.hidden = false;
  }
});
window.omnideckDesktop.onState(render);
