(() => {
  let listener = null;
  let running = false;

  function core() {
    const value = window.__TAURI__?.core;
    if (!value?.invoke || !value?.Channel) {
      throw new Error('The Tauri host bridge is unavailable.');
    }
    return value;
  }

  function stateChannel() {
    const channel = new (core().Channel)();
    channel.onmessage = (state) => listener?.(state);
    return channel;
  }

  async function run(command, args = {}) {
    if (running) return;
    running = true;
    try {
      return await core().invoke(command, args);
    } finally {
      running = false;
    }
  }

  function beginSetup() {
    return run('begin_setup', { onEvent: stateChannel() });
  }

  window.omnideckHost = Object.freeze({
    beginSetup,
    retry: beginSetup,
    openApp: () => run('open_app'),
    runAction: (action) => run('run_action', { action }),
    onState(callback) {
      listener = callback;
      return () => {
        if (listener === callback) listener = null;
      };
    },
  });

  function reportBootstrapFailure(error) {
    // Reuse the setup screen's existing action-error affordance. This keeps a
    // rejected automatic bootstrap visible without adding a new UI state or
    // changing the setup copy/DOM contract.
    const actionError = document.getElementById('action-error');
    if (!actionError) return;
    actionError.textContent = String(error?.message || error);
    actionError.hidden = false;
  }

  async function bootstrap() {
    try {
      const result = await run('bootstrap', { onEvent: stateChannel() });
      if (result?.action === 'setup') await beginSetup(result.reason);
    } catch (error) {
      reportBootstrapFailure(error);
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => void bootstrap(), 0);
  }, { once: true });
})();
