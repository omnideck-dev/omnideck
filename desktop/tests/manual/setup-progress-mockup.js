(() => {
  const PHASES_WITH_ENVIRONMENT = [
    { id: 'software', label: 'Computer setup' },
    { id: 'environment', label: 'Secure space' },
    { id: 'download', label: 'Application files' },
    { id: 'startup', label: 'Final checks' },
  ];
  const PHASES_LINUX = PHASES_WITH_ENVIRONMENT.filter((phase) => phase.id !== 'environment');

  const FLOWS = {
    windows: {
      label: 'Windows',
      phases: PHASES_WITH_ENVIRONMENT,
      permissionDetail: 'Your computer will ask you to approve turning on Windows Subsystem for Linux, which omnideck needs to run in an isolated space. omnideck never sees or stores your password.',
      stages: [
        {
          id: 'wsl-permission',
          label: 'Approve WSL',
          phase: 'software',
          mode: 'permission',
          activity: 'Waiting for approval in Windows Security…',
          status: 'Approval required',
          error: {
            result: 'Permission needed',
            title: 'Windows approval wasn’t granted',
            detail: 'The Windows security prompt was cancelled. Try again and choose Yes to continue setup.',
            value: 'Approval cancelled',
            technical: 'WSL_SETUP_PERMISSION_CANCELLED: Windows returned ERROR_CANCELLED (1223).',
          },
        },
        {
          id: 'wsl-enable',
          label: 'Enable WSL',
          phase: 'software',
          mode: 'indeterminate',
          activity: 'Enabling Windows Subsystem for Linux…',
          status: 'Enabling Windows features',
          error: {
            result: 'Windows feature issue',
            title: 'Windows features couldn’t be enabled',
            detail: 'Approval was granted, but Windows couldn’t finish enabling WSL. Install pending Windows updates, restart the computer, then try again.',
            value: 'WSL unavailable',
            technical: 'WSL_FEATURE_ENABLE_FAILED: wsl.exe returned exit code 1 while enabling VirtualMachinePlatform.',
          },
        },
        {
          id: 'windows-restart',
          label: 'Restart',
          phase: 'software',
          mode: 'restart',
          activity: '',
          status: 'Restart required',
          error: {
            result: 'Restart issue',
            title: 'Windows couldn’t schedule the restart',
            detail: 'Save your work and restart Windows from the Start menu. omnideck will continue after you sign in.',
            value: 'Restart not scheduled',
            technical: 'RESTART_REQUEST_FAILED: shutdown.exe returned access denied while scheduling the restart.',
          },
        },
        {
          id: 'podman-download',
          label: 'Download Podman',
          phase: 'software',
          mode: 'exact',
          activity: 'Downloading Podman…',
          status: '38.4 MB of 82.1 MB',
          sampleProgress: 0.47,
          error: {
            result: 'Download issue',
            title: 'Podman’s download didn’t finish',
            detail: 'Check your internet connection and try again. Anything already downloaded will be reused.',
            value: 'Interrupted',
            technical: 'PODMAN_DOWNLOAD_FAILED: connection reset after 38.4 MB of 82.1 MB.',
          },
        },
        {
          id: 'podman-install',
          label: 'Install Podman',
          phase: 'software',
          mode: 'indeterminate',
          activity: 'Installing Podman…',
          status: 'Installer running',
          error: {
            result: 'Installer issue',
            title: 'Podman couldn’t be installed',
            detail: 'Restart Windows and try again. Technical details include the installer’s result.',
            value: 'Install failed',
            technical: 'PODMAN_MSI_FAILED: Windows Installer returned exit code 1603. Log: podman-install.log.',
          },
        },
        {
          id: 'secure-space',
          label: 'Secure space',
          phase: 'environment',
          mode: 'indeterminate',
          activity: 'Preparing a secure space to run in…',
          status: 'Podman machine starting',
          error: {
            result: 'Environment issue',
            title: 'The secure workspace isn’t responding',
            detail: 'It was created but will not answer. Trying again will attempt to repair it.',
            value: 'Not responding',
            technical: 'PODMAN_MACHINE_TIMEOUT: omnideck-runtime did not become ready within 120 seconds.',
          },
        },
        {
          id: 'app-download',
          label: 'Application files',
          phase: 'download',
          mode: 'exact',
          activity: 'Downloading omnideck’s files…',
          status: '1.8 GB of 3.2 GB',
          sampleProgress: 0.56,
          error: {
            result: 'Download issue',
            title: 'The application download didn’t finish',
            detail: 'Check your internet connection and try again. Anything already downloaded is kept.',
            value: 'Interrupted',
            technical: 'IMAGE_PULL_FAILED: registry request timed out while downloading layer 7 of 11.',
          },
        },
        {
          id: 'startup',
          label: 'Final checks',
          phase: 'startup',
          mode: 'indeterminate',
          activity: 'Starting omnideck and checking its connection…',
          status: 'Checking 127.0.0.1',
          error: {
            result: 'Startup issue',
            title: 'omnideck didn’t finish starting',
            detail: 'Everything installed, but omnideck did not answer in time. Trying again runs the startup checks.',
            value: 'Timed out',
            technical: 'STARTUP_TIMEOUT: http://127.0.0.1:2338 did not return a successful response.',
          },
        },
      ],
    },
    macos: {
      label: 'macOS',
      phases: PHASES_WITH_ENVIRONMENT,
      permissionDetail: 'Your Mac will ask you to approve installing Podman. omnideck never sees or stores your password.',
      stages: [
        {
          id: 'podman-download',
          label: 'Download Podman',
          phase: 'software',
          mode: 'exact',
          activity: 'Downloading Podman…',
          status: '44.7 MB of 96.3 MB',
          sampleProgress: 0.46,
          error: {
            result: 'Download issue',
            title: 'Podman’s download didn’t finish',
            detail: 'Check your internet connection and try again. Anything already downloaded will be reused.',
            value: 'Interrupted',
            technical: 'PODMAN_DOWNLOAD_FAILED: connection reset after 44.7 MB of 96.3 MB.',
          },
        },
        {
          id: 'macos-permission',
          label: 'Approve install',
          phase: 'software',
          mode: 'permission',
          activity: 'Waiting for approval from macOS…',
          status: 'Waiting for approval',
          error: {
            result: 'Permission needed',
            title: 'macOS approval wasn’t granted',
            detail: 'The macOS password prompt was cancelled. Try again and approve it to continue setup.',
            value: 'Approval cancelled',
            technical: 'MACOS_INSTALL_PERMISSION_DENIED: the administrator authorization request was cancelled.',
          },
        },
        {
          id: 'podman-install',
          label: 'Install Podman',
          phase: 'software',
          mode: 'indeterminate',
          activity: 'Installing Podman…',
          status: 'Writing application files',
          error: {
            result: 'Installer issue',
            title: 'Podman couldn’t be installed',
            detail: 'Try again and approve the macOS prompt. Technical details include the installer’s result.',
            value: 'Install failed',
            technical: 'PODMAN_PKG_FAILED: /usr/sbin/installer returned exit code 1.',
          },
        },
        {
          id: 'secure-space',
          label: 'Secure space',
          phase: 'environment',
          mode: 'indeterminate',
          activity: 'Preparing a secure space to run in…',
          status: 'Podman machine starting',
          error: {
            result: 'Environment issue',
            title: 'The secure workspace isn’t responding',
            detail: 'It was created but will not answer. Trying again will attempt to repair it.',
            value: 'Not responding',
            technical: 'PODMAN_MACHINE_TIMEOUT: omnideck-runtime did not become ready within 120 seconds.',
          },
        },
        {
          id: 'app-download',
          label: 'Application files',
          phase: 'download',
          mode: 'exact',
          activity: 'Downloading omnideck’s files…',
          status: '2.1 GB of 3.2 GB',
          sampleProgress: 0.66,
          error: {
            result: 'Download issue',
            title: 'The application download didn’t finish',
            detail: 'Check your internet connection and try again. Anything already downloaded is kept.',
            value: 'Interrupted',
            technical: 'IMAGE_PULL_FAILED: registry request timed out while downloading layer 8 of 11.',
          },
        },
        {
          id: 'startup',
          label: 'Final checks',
          phase: 'startup',
          mode: 'indeterminate',
          activity: 'Starting omnideck and checking its connection…',
          status: 'Checking 127.0.0.1',
          error: {
            result: 'Startup issue',
            title: 'omnideck didn’t finish starting',
            detail: 'Everything installed, but omnideck did not answer in time. Trying again runs the startup checks.',
            value: 'Timed out',
            technical: 'STARTUP_TIMEOUT: http://127.0.0.1:2338 did not return a successful response.',
          },
        },
      ],
    },
    linux: {
      label: 'Linux',
      phases: PHASES_LINUX,
      permissionDetail: 'Your computer will ask you to approve installing Podman — the software omnideck uses to run in an isolated space. omnideck never sees or stores your password.',
      stages: [
        {
          id: 'linux-permission',
          label: 'Approve install',
          phase: 'software',
          mode: 'permission',
          activity: 'Waiting for approval from your computer…',
          status: 'Password required',
          error: {
            result: 'Permission needed',
            title: 'Installation approval wasn’t granted',
            detail: 'Try again and approve your computer’s software-install prompt.',
            value: 'Permission denied',
            technical: 'POLICYKIT_PERMISSION_DENIED: pkexec authorization was dismissed.',
          },
        },
        {
          id: 'package-index',
          label: 'Check packages',
          phase: 'software',
          mode: 'indeterminate',
          activity: 'Checking available software packages…',
          status: 'Package manager running',
          error: {
            result: 'Package manager issue',
            title: 'Available software couldn’t be checked',
            detail: 'Check your package manager and internet connection, then try again.',
            value: 'Update failed',
            technical: 'PACKAGE_INDEX_FAILED: apt-get update returned exit code 100.',
          },
        },
        {
          id: 'podman-install',
          label: 'Install Podman',
          phase: 'software',
          mode: 'indeterminate',
          activity: 'Installing Podman…',
          status: 'Configuring dependencies',
          error: {
            result: 'Installer issue',
            title: 'Podman couldn’t be installed',
            detail: 'Check your package manager and available disk space, then try again.',
            value: 'Install failed',
            technical: 'PODMAN_PACKAGE_FAILED: the distribution package manager returned exit code 1.',
          },
        },
        {
          id: 'app-download',
          label: 'Application files',
          phase: 'download',
          mode: 'exact',
          activity: 'Downloading omnideck’s files…',
          status: '1.4 GB of 3.2 GB',
          sampleProgress: 0.44,
          error: {
            result: 'Download issue',
            title: 'The application download didn’t finish',
            detail: 'Check your internet connection and try again. Anything already downloaded is kept.',
            value: 'Interrupted',
            technical: 'IMAGE_PULL_FAILED: registry request timed out while downloading layer 6 of 11.',
          },
        },
        {
          id: 'startup',
          label: 'Final checks',
          phase: 'startup',
          mode: 'indeterminate',
          activity: 'Starting omnideck and checking its connection…',
          status: 'Checking 127.0.0.1',
          error: {
            result: 'Startup issue',
            title: 'omnideck didn’t finish starting',
            detail: 'Everything installed, but omnideck did not answer in time. Trying again runs the startup checks.',
            value: 'Timed out',
            technical: 'STARTUP_TIMEOUT: http://127.0.0.1:2338 did not return a successful response.',
          },
        },
      ],
    },
  };

  const status = document.getElementById('mockup-status');
  const stageNav = document.getElementById('mockup-stage-nav');
  const previous = document.getElementById('mockup-previous');
  const next = document.getElementById('mockup-next');
  const play = document.getElementById('mockup-play');
  const fail = document.getElementById('mockup-fail');
  const theme = document.getElementById('mockup-theme');
  const progressContext = document.getElementById('progress-context');
  const progressStep = document.getElementById('progress-step');
  const progressValue = document.getElementById('progress-value');
  const toast = document.getElementById('mockup-toast');

  const requestedOS = new URLSearchParams(window.location.search).get('os');
  let selectedOS = Object.hasOwn(FLOWS, requestedOS) ? requestedOS : 'windows';
  let stageIndex = -1;
  let currentState;
  let listener;
  let playing = false;
  let resumed = false;
  let timerIDs = [];
  let toastTimer;

  function flow() {
    return FLOWS[selectedOS];
  }

  function clearPlayback() {
    timerIDs.forEach((timerID) => {
      clearTimeout(timerID);
      clearInterval(timerID);
    });
    timerIDs = [];
    playing = false;
    play.textContent = 'Play happy path';
  }

  function schedule(callback, delay) {
    const timerID = setTimeout(callback, delay);
    timerIDs.push(timerID);
    return timerID;
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 3200);
  }

  function updateThemeLabel() {
    theme.textContent = document.documentElement.dataset.theme === 'dark'
      ? 'Light theme'
      : 'Dark theme';
  }

  function welcomeState() {
    return {
      stage: 'welcome',
      title: 'Welcome to omnideck',
      detail: 'A one-time setup will prepare everything omnideck needs on this computer.',
      canStart: true,
      setupReason: 'first-run',
    };
  }

  function readyState() {
    return {
      stage: 'ready',
      title: 'omnideck is ready',
      detail: 'Everything is prepared. Open omnideck whenever you’re ready.',
      canOpen: true,
      setupReason: resumed ? 'resume' : 'first-run',
    };
  }

  function restartState() {
    return {
      stage: 'error',
      title: 'Restart needed',
      detail: 'Windows must restart to finish enabling required features. Save any open work, then restart now or later. If you restart now, omnideck reopens after you sign in and continues setup.',
      primaryAction: 'restart',
      primaryLabel: 'Restart now',
      secondaryAction: 'close',
      secondaryLabel: 'Restart later',
      setupReason: 'first-run',
      diagnostics: [],
      diagnosticResult: 'Restart required',
    };
  }

  function stageState(stage, fraction = stage.sampleProgress) {
    if (stage.mode === 'restart') return restartState();
    const permission = stage.mode === 'permission';
    return {
      stage: 'preparing',
      title: permission ? 'Waiting for your permission' : 'Preparing your environment',
      detail: permission
        ? flow().permissionDetail
        : resumed
          ? 'Continuing from where the last attempt stopped. Anything already finished is kept.'
          : 'Setting omnideck up on this computer. This usually takes a few minutes.',
      activity: stage.activity,
      progress: stage.mode === 'exact' ? fraction : undefined,
      indeterminate: stage.mode === 'indeterminate',
      setupReason: resumed ? 'resume' : 'first-run',
    };
  }

  function errorState(stage) {
    const failedIndex = flow().phases.findIndex((phase) => phase.id === stage.phase);
    const diagnostics = flow().phases.map((phase, index) => {
      if (index === failedIndex) {
        return { id: phase.id, label: phase.label, status: 'issue', value: stage.error.value };
      }
      const passed = index < failedIndex;
      return {
        id: phase.id,
        label: phase.label,
        status: passed ? 'pass' : 'waiting',
        value: passed ? 'Done' : 'Not started',
      };
    });
    return {
      stage: 'error',
      title: stage.error.title,
      detail: stage.error.detail,
      canRetry: true,
      setupReason: resumed ? 'resume' : 'first-run',
      diagnostics,
      diagnosticResult: stage.error.result,
      technical: stage.error.technical,
    };
  }

  function updateSupplemental(state, stage, fraction) {
    const active = state.stage === 'preparing' && stage;
    progressContext.hidden = !active;
    if (active) {
      progressStep.textContent = `Step ${stageIndex + 1} of ${flow().stages.length}`;
      progressValue.textContent = stage.mode === 'exact'
        ? `${Math.round((fraction ?? stage.sampleProgress ?? 0) * 100)}% · ${stage.status}`
        : stage.status;
    }

    status.textContent = `${flow().label} · ${stageIndex < 0 ? 'Welcome' : stageIndex >= flow().stages.length ? 'Ready' : stage.label}`;
    fail.disabled = stageIndex < 0 || stageIndex >= flow().stages.length;
    fail.textContent = stage ? `Trigger ${stage.label} error` : 'Trigger stage error';
    previous.disabled = stageIndex < 0;
    next.textContent = stageIndex >= flow().stages.length ? 'Start over' : 'Next';

    stageNav.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-current', Number(button.dataset.stageIndex) === stageIndex ? 'step' : 'false');
    });
  }

  function emit(state, stage, fraction) {
    currentState = state;
    updateSupplemental(state, stage, fraction);
    listener?.(state);
  }

  function renderWelcome() {
    clearPlayback();
    resumed = false;
    stageIndex = -1;
    emit(welcomeState());
  }

  function renderReady() {
    clearPlayback();
    stageIndex = flow().stages.length;
    emit(readyState());
  }

  function renderStage(index, autoplay = false) {
    timerIDs.forEach((timerID) => {
      clearTimeout(timerID);
      clearInterval(timerID);
    });
    timerIDs = [];
    stageIndex = Math.max(0, Math.min(index, flow().stages.length - 1));
    const stage = flow().stages[stageIndex];

    if (stage.mode === 'exact' && autoplay) {
      let fraction = 0.08;
      emit(stageState(stage, fraction), stage, fraction);
      const intervalID = setInterval(() => {
        fraction = Math.min(1, fraction + 0.075);
        emit(stageState(stage, fraction), stage, fraction);
        if (fraction >= 1) {
          clearInterval(intervalID);
          schedule(advanceHappyPath, 650);
        }
      }, 120);
      timerIDs.push(intervalID);
      return;
    }

    emit(stageState(stage), stage, stage.sampleProgress);
    if (!autoplay) return;

    if (stage.mode === 'restart') {
      schedule(() => {
        showToast('Windows restarts, omnideck reopens, and setup continues after sign-in.');
        resumed = true;
        advanceHappyPath();
      }, 2400);
      return;
    }
    schedule(advanceHappyPath, stage.mode === 'permission' ? 1900 : 1650);
  }

  function advanceHappyPath() {
    if (!playing) return;
    const nextIndex = stageIndex + 1;
    if (nextIndex >= flow().stages.length) {
      renderReady();
      return;
    }
    renderStage(nextIndex, true);
  }

  function startHappyPath(startAt = 0) {
    clearPlayback();
    playing = true;
    resumed = false;
    play.textContent = 'Playing happy path…';
    renderStage(startAt, true);
  }

  function selectStage(index) {
    clearPlayback();
    if (index < 0) renderWelcome();
    else if (index >= flow().stages.length) renderReady();
    else renderStage(index);
  }

  function triggerCurrentError() {
    if (stageIndex < 0 || stageIndex >= flow().stages.length) return;
    clearPlayback();
    const stage = flow().stages[stageIndex];
    emit(errorState(stage), stage);
  }

  function rebuildStageNavigation() {
    const entries = [
      { label: 'Welcome', index: -1 },
      ...flow().stages.map((stage, index) => ({ label: stage.label, index })),
      { label: 'Ready', index: flow().stages.length },
    ];
    stageNav.replaceChildren(...entries.map((entry) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = entry.label;
      button.dataset.stageIndex = String(entry.index);
      button.addEventListener('click', () => selectStage(entry.index));
      return button;
    }));
  }

  function selectOS(os) {
    selectedOS = os;
    document.querySelectorAll('[data-os]').forEach((button) => {
      button.setAttribute('aria-selected', String(button.dataset.os === os));
    });
    rebuildStageNavigation();
    renderWelcome();
  }

  document.querySelectorAll('[data-os]').forEach((button) => {
    button.addEventListener('click', () => selectOS(button.dataset.os));
  });
  previous.addEventListener('click', () => selectStage(stageIndex - 1));
  next.addEventListener('click', () => {
    if (stageIndex >= flow().stages.length) renderWelcome();
    else selectStage(stageIndex + 1);
  });
  play.addEventListener('click', () => startHappyPath());
  fail.addEventListener('click', triggerCurrentError);
  theme.addEventListener('click', () => {
    const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = nextTheme;
    updateThemeLabel();
  });

  window.omnideckHost = Object.freeze({
    beginSetup() {
      startHappyPath();
      return Promise.resolve();
    },
    retry() {
      renderStage(Math.max(0, stageIndex));
      showToast('Retrying this stage; completed work is kept.');
      return Promise.resolve();
    },
    openApp() {
      showToast('Opening omnideck…');
      return Promise.resolve();
    },
    runAction(action) {
      if (action === 'restart') {
        resumed = true;
        showToast('Windows restarts, omnideck reopens, and setup continues after sign-in.');
        renderStage(Math.min(stageIndex + 1, flow().stages.length - 1));
      } else if (action === 'close') {
        showToast('Setup closes and will continue after the next restart.');
      }
      return Promise.resolve();
    },
    onState(callback) {
      listener = callback;
      queueMicrotask(() => {
        updateThemeLabel();
        callback(currentState);
      });
      return () => {
        if (listener === callback) listener = undefined;
      };
    },
  });

  document.querySelectorAll('[data-os]').forEach((button) => {
    button.setAttribute('aria-selected', String(button.dataset.os === selectedOS));
  });
  rebuildStageNavigation();
  currentState = welcomeState();
  updateSupplemental(currentState);
})();
