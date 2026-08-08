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

  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => void run('bootstrap', { onEvent: stateChannel() }), 0);
  }, { once: true });
})();
