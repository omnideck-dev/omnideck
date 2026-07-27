const diagnosticOrder = [
  'Computer support',
  'Required components',
  'Required downloads',
  'Local environment',
  'Release files',
  'omnideck startup',
];

function diagnosticResults(overrides = {}) {
  return diagnosticOrder.map((label) => ({
    label,
    status: 'waiting',
    value: 'Not checked',
    ...overrides[label],
  }));
}

const screens = [
  {
    id: 'welcome',
    group: 'First-time setup',
    name: 'Welcome',
    stage: 'welcome',
    eyebrow: 'WELCOME',
    title: 'Welcome to omnideck',
    detail: 'A one-time setup will prepare everything omnideck needs on this computer.',
    primary: 'Set up omnideck',
    note: 'The first visible screen on a new installation. No pre-welcome checking screen.',
  },
  {
    id: 'preparing',
    group: 'First-time setup',
    name: 'Preparing environment',
    stage: 'preparing',
    eyebrow: 'FIRST-TIME SETUP',
    title: 'Preparing your environment',
    detail: 'Downloading and installing required components. This may take several minutes.',
    indeterminate: true,
    game: true,
    note: 'One continuous state covers every underlying download, installation, image pull, and environment-creation step.',
  },
  {
    id: 'permission',
    group: 'First-time setup',
    name: 'System permission',
    stage: 'preparing',
    eyebrow: 'FIRST-TIME SETUP',
    title: 'Preparing your environment',
    detail: 'Your computer may ask for permission to install required components. omnideck never sees or stores your password.',
    indeterminate: true,
    game: true,
    note: 'The same generic message is used on Windows, macOS, and Linux. The operating system owns the actual prompt.',
  },
  {
    id: 'finishing',
    group: 'First-time setup',
    name: 'Finishing setup',
    stage: 'starting',
    eyebrow: 'FIRST-TIME SETUP',
    title: 'Finishing setup',
    detail: 'Getting everything ready…',
    indeterminate: true,
    game: true,
    note: 'Covers storage creation, local configuration, startup, and readiness checks. There is no separate Opening screen.',
  },
  {
    id: 'ready',
    group: 'First-time setup',
    name: 'Ready',
    stage: 'ready',
    eyebrow: 'READY',
    title: 'omnideck is ready',
    detail: 'Everything is prepared. Open omnideck whenever you’re ready.',
    progress: 1,
    primary: 'Open omnideck',
    game: true,
    note: 'omnideck waits here so the user can keep playing Agent Dash before opening the app.',
  },
  {
    id: 'update',
    group: 'Manual app upgrade',
    name: 'Applying an update',
    stage: 'preparing',
    eyebrow: 'UPDATING',
    title: 'Preparing your environment',
    detail: 'Applying the latest updates… This may take several minutes.',
    indeterminate: true,
    game: true,
    note: 'Shown only after installing an app version pinned to a newer environment image. Normal returning launches open directly.',
  },
  {
    id: 'update-finishing',
    group: 'Manual app upgrade',
    name: 'Finishing update',
    stage: 'starting',
    eyebrow: 'UPDATING',
    title: 'Finishing setup',
    detail: 'Getting everything ready…',
    indeterminate: true,
    game: true,
    note: 'Persistent user data is preserved while the prepared environment is replaced.',
  },
  {
    id: 'update-ready',
    group: 'Manual app upgrade',
    name: 'Update ready',
    stage: 'ready',
    eyebrow: 'READY',
    title: 'omnideck is ready',
    detail: 'Everything is prepared. Open omnideck whenever you’re ready.',
    progress: 1,
    primary: 'Open omnideck',
    game: true,
    note: 'The same Ready screen concludes first-time setup, interrupted-setup recovery, and manual upgrades.',
  },
  {
    id: 'doctor-support',
    group: 'Doctor',
    name: 'Computer not supported',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'This computer isn’t supported yet',
    detail: 'This version of omnideck can’t prepare the required environment on this computer.',
    primary: 'View supported systems',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Compatibility issue',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'issue', value: 'Not supported' },
      'Release files': { status: 'pass', value: 'Verified' },
    }),
    technical: 'architecture check: this operating-system and CPU combination is not included in the current desktop release',
    note: 'Backed by the existing platform/architecture and Linux-distribution checks.',
  },
  {
    id: 'doctor-components',
    group: 'Doctor',
    name: 'Component unavailable',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'omnideck needs attention',
    detail: 'A required component couldn’t be installed or started. Try setup again.',
    primary: 'Try again',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Component issue',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'pass', value: 'Supported' },
      'Required components': { status: 'issue', value: 'Unavailable' },
      'Release files': { status: 'pass', value: 'Verified' },
    }),
    technical: 'runtime check: required executable was not found after installation',
    note: 'Backed by executable discovery, installer verification, and the runtime health command.',
  },
  {
    id: 'doctor-permission',
    group: 'Doctor',
    name: 'Permission denied',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'omnideck needs attention',
    detail: 'Permission wasn’t granted. Try again and approve the request from your computer.',
    primary: 'Try again',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Permission needed',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'pass', value: 'Supported' },
      'Required components': { status: 'issue', value: 'Permission denied' },
      'Release files': { status: 'pass', value: 'Verified' },
    }),
    technical: 'system installer: the operating-system permission request was cancelled or denied',
    note: 'Backed by the existing permission, authorization, authentication, and cancellation error classification.',
  },
  {
    id: 'doctor-download',
    group: 'Doctor',
    name: 'Download failed',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'omnideck needs attention',
    detail: 'A required download didn’t finish. Check your connection and try again.',
    primary: 'Try again',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Download issue',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'pass', value: 'Supported' },
      'Required components': { status: 'pass', value: 'Ready' },
      'Required downloads': { status: 'issue', value: 'Interrupted' },
      'Local environment': { status: 'pass', value: 'Ready' },
      'Release files': { status: 'pass', value: 'Verified' },
    }),
    technical: 'download application: the pinned release files were not available before the connection closed',
    note: 'Backed by HTTP download failures and the digest-pinned image pull. Cached files and image layers are reused on retry.',
  },
  {
    id: 'doctor-environment',
    group: 'Doctor',
    name: 'Environment unavailable',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'omnideck needs attention',
    detail: 'The local environment isn’t responding. Try again to repair it.',
    primary: 'Try again',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Environment issue',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'pass', value: 'Supported' },
      'Required components': { status: 'pass', value: 'Installed' },
      'Local environment': { status: 'issue', value: 'Not responding' },
      'Release files': { status: 'pass', value: 'Verified' },
    }),
    technical: 'runtime check exited with a non-zero status\nlocal environment health information was unavailable',
    note: 'Backed by the runtime info command and, on macOS/Windows, local-machine inspection and startup.',
  },
  {
    id: 'doctor-release',
    group: 'Doctor',
    name: 'Release files invalid',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'Download omnideck again',
    detail: 'This installer is incomplete or damaged. Download a fresh copy before trying again.',
    primary: 'Download omnideck',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Installer issue',
    diagnostics: diagnosticResults({
      'Release files': { status: 'issue', value: 'Invalid' },
    }),
    technical: 'image-manifest.json: release version or immutable image digest validation failed',
    note: 'Backed by the packaged runtime-manifest schema, app-version, and digest-reference checks.',
  },
  {
    id: 'doctor-startup',
    group: 'Doctor',
    name: 'Startup timed out',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'omnideck needs attention',
    detail: 'Setup finished, but omnideck didn’t start. Try again to run the startup checks.',
    primary: 'Try again',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Startup issue',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'pass', value: 'Supported' },
      'Required components': { status: 'pass', value: 'Ready' },
      'Required downloads': { status: 'pass', value: 'Available' },
      'Local environment': { status: 'pass', value: 'Running' },
      'Release files': { status: 'pass', value: 'Verified' },
      'omnideck startup': { status: 'issue', value: 'Timed out' },
    }),
    technical: 'app readiness check: the local HTTP endpoint did not become ready within 120 seconds',
    note: 'Backed by the real loopback HTTP readiness probe and its two-minute deadline.',
  },
  {
    id: 'doctor-restart',
    group: 'Doctor',
    name: 'Windows restart',
    platform: 'windows',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'Restart needed',
    detail: 'Restart your computer, then open omnideck to continue setup.',
    primary: 'Close omnideck',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Restart required',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'pass', value: 'Supported' },
      'Required components': { status: 'issue', value: 'Restart needed' },
      'Release files': { status: 'pass', value: 'Verified' },
    }),
    technical: 'Windows workspace check: WSL 2 was enabled and Windows reported that a system restart is required',
    note: 'Backed by the WSL status and installer exit-code checks. Setup resumes automatically after reopening omnideck.',
  },
  {
    id: 'doctor-unknown',
    group: 'Doctor',
    name: 'Unexpected issue',
    stage: 'error',
    eyebrow: 'SETUP NEEDS ATTENTION',
    title: 'omnideck needs attention',
    detail: 'Setup didn’t finish. Try again, or open the diagnostic log if the issue continues.',
    primary: 'Try again',
    secondary: 'Open diagnostic log',
    game: true,
    doctorResult: 'Setup issue',
    diagnostics: diagnosticResults({
      'Computer support': { status: 'pass', value: 'Supported' },
      'Required components': { status: 'pass', value: 'Ready' },
      'Release files': { status: 'pass', value: 'Verified' },
    }),
    technical: 'unexpected setup failure\nfull child-process output and timestamps are available in desktop.log',
    note: 'Fallback for failures that do not match a specific real diagnostic category.',
  },
];

const reviewKey = 'omnideck-setup-flow-review-v2';
const storedReview = JSON.parse(localStorage.getItem(reviewKey) || '{}');
const approvals = new Set(storedReview.approvals || []);
const notes = storedReview.notes || {};

const screenList = document.getElementById('screen-list');
const previewStage = document.getElementById('preview-stage');
const flowName = document.getElementById('flow-name');
const screenName = document.getElementById('screen-name');
const position = document.getElementById('screen-position');
const approvalCount = document.getElementById('approval-count');
const implementationNote = document.getElementById('implementation-note');
const reviewNote = document.getElementById('review-note');
const approve = document.getElementById('approve');
const copySummary = document.getElementById('copy-summary');
const previous = document.getElementById('previous');
const next = document.getElementById('next');
const eyebrow = document.getElementById('eyebrow');
const setupTitle = document.getElementById('setup-title');
const detail = document.getElementById('detail');
const doctorPanel = document.getElementById('doctor-panel');
const doctorResult = document.getElementById('doctor-result');
const diagnosticList = document.getElementById('diagnostic-list');
const technicalDetails = document.getElementById('technical-details');
const technicalOutput = document.getElementById('technical-output');
const progressWrap = document.getElementById('progress-wrap');
const progressTrack = document.getElementById('progress-track');
const progress = document.getElementById('progress');
const spinner = document.getElementById('spinner');
const primary = document.getElementById('primary');
const logs = document.getElementById('logs');
const footnote = document.getElementById('footnote');
const toast = document.getElementById('toast');

let currentIndex = Math.max(0, screens.findIndex((screen) => `#${screen.id}` === location.hash));
let toastTimer;

function persistReview() {
  localStorage.setItem(reviewKey, JSON.stringify({
    approvals: [...approvals],
    notes,
  }));
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 1800);
}

function setupState(screen) {
  return {
    stage: screen.stage,
    progress: Number.isFinite(screen.progress) ? screen.progress : null,
    indeterminate: Boolean(screen.indeterminate),
  };
}

function renderScreenList() {
  const groups = [...new Set(screens.map((screen) => screen.group))];
  screenList.replaceChildren(...groups.map((group) => {
    const section = document.createElement('section');
    section.className = 'screen-group';
    const heading = document.createElement('h2');
    heading.textContent = group;
    section.append(heading);

    screens.forEach((screen, index) => {
      if (screen.group !== group) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'screen-link';
      button.dataset.index = String(index);

      const number = document.createElement('span');
      number.className = 'screen-number';
      number.textContent = String(index + 1).padStart(2, '0');
      const label = document.createElement('span');
      label.textContent = `${screen.name}${screen.platform ? ` · ${screen.platform}` : ''}`;
      const mark = document.createElement('span');
      mark.className = 'approval-mark';
      mark.textContent = approvals.has(screen.id) ? '✓' : '○';
      mark.setAttribute('aria-label', approvals.has(screen.id) ? 'Approved' : 'Not approved');

      button.append(number, label, mark);
      button.addEventListener('click', () => selectScreen(index));
      section.append(button);
    });
    return section;
  }));
}

function renderDiagnostics(screen) {
  doctorPanel.hidden = !screen.diagnostics;
  diagnosticList.replaceChildren();
  technicalDetails.open = false;
  if (!screen.diagnostics) return;

  doctorResult.textContent = screen.doctorResult;
  technicalOutput.textContent = screen.technical;
  diagnosticList.replaceChildren(...screen.diagnostics.map((diagnostic) => {
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

function render() {
  const screen = screens[currentIndex];
  document.documentElement.dataset.stage = screen.stage;
  location.hash = screen.id;
  flowName.textContent = screen.group;
  screenName.textContent = screen.name;
  position.textContent = `${currentIndex + 1} of ${screens.length}`;
  approvalCount.textContent = `${approvals.size} approved`;
  implementationNote.textContent = screen.note;
  reviewNote.value = notes[screen.id] || '';
  approve.textContent = approvals.has(screen.id) ? '✓ Screen approved' : 'Approve this screen';
  approve.classList.toggle('is-approved', approvals.has(screen.id));

  eyebrow.textContent = screen.eyebrow;
  setupTitle.textContent = screen.title;
  detail.textContent = screen.detail;
  renderDiagnostics(screen);

  const hasProgress = Number.isFinite(screen.progress);
  const hasIndeterminateProgress = Boolean(screen.indeterminate);
  progressWrap.hidden = !(hasProgress || hasIndeterminateProgress);
  progressWrap.classList.toggle('is-indeterminate', hasIndeterminateProgress);
  progress.style.width = hasProgress ? `${Math.round(screen.progress * 100)}%` : '';
  if (hasProgress) {
    progressTrack.setAttribute('aria-valuenow', String(Math.round(screen.progress * 100)));
    progressTrack.removeAttribute('aria-valuetext');
  } else {
    progressTrack.removeAttribute('aria-valuenow');
    if (hasIndeterminateProgress) progressTrack.setAttribute('aria-valuetext', 'In progress');
    else progressTrack.removeAttribute('aria-valuetext');
  }

  spinner.hidden = !screen.spinner;
  primary.hidden = !screen.primary;
  primary.textContent = screen.primary || '';
  logs.hidden = !screen.secondary;
  logs.textContent = screen.secondary || '';
  footnote.hidden = ['error', 'ready'].includes(screen.stage);

  previous.disabled = currentIndex === 0;
  next.disabled = currentIndex === screens.length - 1;

  document.querySelectorAll('.screen-link').forEach((button) => {
    const index = Number(button.dataset.index);
    button.classList.toggle('is-current', index === currentIndex);
    button.classList.toggle('is-approved', approvals.has(screens[index].id));
    const mark = button.querySelector('.approval-mark');
    mark.textContent = approvals.has(screens[index].id) ? '✓' : '○';
    mark.setAttribute('aria-label', approvals.has(screens[index].id) ? 'Approved' : 'Not approved');
  });

  if (screen.game) globalThis.agentDashSetupState?.({ stage: 'preparing' });
  globalThis.agentDashSetupState?.(setupState(screen));
}

function selectScreen(index) {
  currentIndex = Math.max(0, Math.min(screens.length - 1, index));
  render();
  document.querySelector(`.screen-link[data-index="${currentIndex}"]`)?.scrollIntoView({
    block: 'nearest',
  });
}

function reviewSummary() {
  const lines = [
    'omnideck setup flow review',
    '',
  ];
  for (const [index, screen] of screens.entries()) {
    lines.push(`${approvals.has(screen.id) ? 'APPROVED' : 'PENDING'} ${index + 1}. ${screen.group} — ${screen.name}`);
    lines.push(`Title: ${screen.title}`);
    lines.push(`Message: ${screen.detail}`);
    if (screen.diagnostics) {
      lines.push(`Diagnostic result: ${screen.doctorResult}`);
      for (const diagnostic of screen.diagnostics) {
        lines.push(`- ${diagnostic.label}: ${diagnostic.value}`);
      }
    }
    if (notes[screen.id]) lines.push(`Feedback: ${notes[screen.id]}`);
    lines.push('');
  }
  return lines.join('\n');
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall back for file:// previews and browsers without clipboard permission.
    }
  }
  const field = document.createElement('textarea');
  field.value = value;
  field.setAttribute('readonly', '');
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.append(field);
  field.select();
  document.execCommand('copy');
  field.remove();
}

previous.addEventListener('click', () => selectScreen(currentIndex - 1));
next.addEventListener('click', () => selectScreen(currentIndex + 1));
primary.addEventListener('click', () => {
  if (currentIndex < screens.length - 1) selectScreen(currentIndex + 1);
});
reviewNote.addEventListener('input', () => {
  const screen = screens[currentIndex];
  if (reviewNote.value.trim()) notes[screen.id] = reviewNote.value.trim();
  else delete notes[screen.id];
  persistReview();
});
approve.addEventListener('click', () => {
  const id = screens[currentIndex].id;
  if (approvals.has(id)) approvals.delete(id);
  else approvals.add(id);
  persistReview();
  render();
});
copySummary.addEventListener('click', async () => {
  await copyText(reviewSummary());
  showToast('Review summary copied');
});
document.querySelectorAll('.view-button').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.view-button').forEach((candidate) => {
      candidate.classList.toggle('is-selected', candidate === button);
    });
    previewStage.classList.toggle('compact', button.dataset.view === 'compact');
  });
});
document.addEventListener('keydown', (event) => {
  if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
  if (event.key === 'ArrowLeft') selectScreen(currentIndex - 1);
  if (event.key === 'ArrowRight') selectScreen(currentIndex + 1);
});
window.addEventListener('hashchange', () => {
  const index = screens.findIndex((screen) => `#${screen.id}` === location.hash);
  if (index >= 0 && index !== currentIndex) selectScreen(index);
});

const query = new URLSearchParams(location.search);
if (query.get('view') === 'compact') {
  previewStage.classList.add('compact');
  document.querySelectorAll('.view-button').forEach((button) => {
    button.classList.toggle('is-selected', button.dataset.view === 'compact');
  });
}

renderScreenList();
render();
