(() => {
  const messageType = 'omnideck:open-external';

  const externalHttpUrl = (href) => {
    if (typeof href !== 'string' || !href) return null;
    try {
      const url = new URL(href, window.location.href);
      if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
      return url.origin === window.location.origin ? null : url;
    } catch (_error) {
      return null;
    }
  };

  const openExternal = (href) => {
    const url = externalHttpUrl(href);
    if (!url || typeof window.omnideckHost?.openExternal !== 'function') return false;
    Promise.resolve(window.omnideckHost.openExternal(url.href)).catch((error) => {
      console.error('Could not open external link.', error);
    });
    return true;
  };

  window.addEventListener('click', (event) => {
    const anchor = event.target?.closest?.('a[href]');
    if (!anchor || anchor.hasAttribute('download')) return;
    const url = externalHttpUrl(anchor.href);
    if (!url) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (window === window.top) {
      openExternal(url.href);
    } else {
      window.top.postMessage({ type: messageType, url: url.href }, window.location.origin);
    }
  }, { capture: true });

  if (window !== window.top) return;
  window.addEventListener('message', (event) => {
    if (event.source === window || event.origin !== window.location.origin) return;
    if (event.data?.type !== messageType || typeof event.data.url !== 'string') return;
    openExternal(event.data.url);
  });
})();
