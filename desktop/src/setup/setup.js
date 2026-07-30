const title = document.getElementById('title');
const detail = document.getElementById('detail');
const eyebrow = document.getElementById('eyebrow');
const primary = document.getElementById('primary');
const secondary = document.getElementById('secondary');
const spinner = document.getElementById('spinner');
const progressWrap = document.getElementById('progress-wrap');
const progressTrack = progressWrap.querySelector('[role="progressbar"]');
const progress = document.getElementById('progress');
const footnote = document.getElementById('footnote');
const doctorPanel = document.getElementById('doctor-panel');
const doctorKicker = document.getElementById('doctor-kicker');
const doctorResult = document.getElementById('doctor-result');
const technicalDetails = document.getElementById('technical-details');
const diagnosticList = document.getElementById('diagnostic-list');
const technicalOutput = document.getElementById('technical-output');
const actionError = document.getElementById('action-error');

let currentState = { stage: 'welcome' };

// The application seeds its theme from the OS preference and mirrors it onto a
// data-theme attribute that the CSS layer keys off. This screen cannot read the
// application's stored choice — it runs from the filesystem, a different origin
// — so the OS preference is the whole of it.
const darkQuery = window.matchMedia?.('(prefers-color-scheme: dark)');

function applyTheme() {
  document.documentElement.dataset.theme = darkQuery?.matches ? 'dark' : 'light';
}

applyTheme();
darkQuery?.addEventListener?.('change', applyTheme);

const DIAGNOSTIC_ICONS = { pass: '✓', issue: '!', working: '›' };
const STAGE_EYEBROWS = {
  ready: 'READY',
  error: 'SETUP NEEDS ATTENTION',
  welcome: 'WELCOME',
};
const REASON_EYEBROWS = {
  update: 'UPDATING',
  repair: 'PREPARING',
  resume: 'CONTINUING SETUP',
};
// Stages where a wait is actually happening, so the note about filling it is
// true. Notably not the opening splash: a returning user is a second from the
// app and is not setting anything up.
const FOOTNOTE_STAGES = ['welcome', 'preparing', 'finishing'];
// Stages that are showing an outcome rather than work in progress.
const SETTLED_STAGES = ['welcome', 'error', 'ready'];

function eyebrowFor(state) {
  return STAGE_EYEBROWS[state.stage]
    || REASON_EYEBROWS[state.setupReason]
    || 'FIRST-TIME SETUP';
}

// The same list serves two jobs: a checklist of where setup has got to, and the
// report of which step failed. Only the heading and the technical block differ.
function renderDiagnostics(state) {
  const diagnostics = Array.isArray(state.diagnostics) ? state.diagnostics : [];
  const failed = state.stage === 'error';
  doctorPanel.hidden = diagnostics.length === 0;
  document.documentElement.dataset.checklist = doctorPanel.hidden ? '' : 'shown';
  diagnosticList.replaceChildren();
  if (doctorPanel.hidden) return;

  doctorPanel.dataset.mode = failed ? 'diagnostics' : 'progress';
  doctorKicker.textContent = failed ? 'DIAGNOSTICS' : 'PROGRESS';
  doctorResult.hidden = !failed;
  doctorResult.textContent = state.diagnosticResult || 'Issue found';
  technicalDetails.hidden = !failed;
  technicalDetails.open = false;
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

  secondary.hidden = !state.secondaryAction;
  secondary.textContent = state.secondaryLabel || '';
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
  spinner.hidden = progressWrap.hidden === false || SETTLED_STAGES.includes(state.stage);
  footnote.hidden = !FOOTNOTE_STAGES.includes(state.stage);
  window.agentDashSetupState?.(state);
}

function runPrimaryAction() {
  if (currentState.primaryAction) {
    return window.omnideckDesktop.runAction(currentState.primaryAction);
  }
  if (currentState.canOpen) return window.omnideckDesktop.openApp();
  if (currentState.canRetry) return window.omnideckDesktop.retry();
  return window.omnideckDesktop.beginSetup();
}

function reportActionFailure(error) {
  actionError.textContent = String(error?.message || error);
  actionError.hidden = false;
}

// Re-enabling in a finally matters: the button is only otherwise re-enabled by
// the next state push, and a rejected action does not always produce one. That
// left the single control on the screen dead with nothing explaining why.
primary.addEventListener('click', async () => {
  primary.disabled = true;
  actionError.hidden = true;
  try {
    await runPrimaryAction();
  } catch (error) {
    reportActionFailure(error);
  } finally {
    primary.disabled = false;
  }
});

secondary.addEventListener('click', async () => {
  if (!currentState.secondaryAction) return;
  secondary.disabled = true;
  actionError.hidden = true;
  try {
    await window.omnideckDesktop.runAction(currentState.secondaryAction);
  } catch (error) {
    reportActionFailure(error);
  } finally {
    secondary.disabled = false;
  }
});
window.omnideckDesktop.onState(render);
