"""Shared browser-side detection for modal interaction surfaces."""

from __future__ import annotations

# Keep this as plain JavaScript function declarations so it can be embedded in
# both the renderer's one-round-trip DOM walk and scrolling's state checks.
# A modal is either semantic (native top-layer dialog or an ARIA dialog whose
# background is actually suppressed) or a conservative custom-overlay match:
# the body is scroll-locked and a visible fixed element covers most of the
# viewport while looking like a dialog.
#
# ``aria-modal`` is only an accessibility declaration. It becomes evidence of
# an active modal here only when the page also suppresses the background.
MODAL_HELPERS_JS = r"""
  function omnideckElementIsVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && parseFloat(style.opacity || '1') > 0
      && rect.bottom > 0
      && rect.top < window.innerHeight
      && rect.right > 0
      && rect.left < window.innerWidth
      && rect.width > 0
      && rect.height > 0;
  }

  function omnideckSemanticModal() {
    let candidates = [];
    try {
      candidates = Array.from(document.querySelectorAll(
        'dialog:modal,'
        + '[role="dialog"][aria-modal="true"],'
        + '[role="alertdialog"][aria-modal="true"]'
      ));
    } catch (_error) {
      candidates = Array.from(document.querySelectorAll(
        '[role="dialog"][aria-modal="true"],'
        + '[role="alertdialog"][aria-modal="true"]'
      ));
    }
    candidates = candidates.filter((element) => {
      if (!omnideckElementIsVisible(element)) return false;
      if (element.tagName === 'DIALOG') return true;
      return omnideckAriaDialogSuppressesBackground(element);
    });
    const element = candidates.length > 0 ? candidates[candidates.length - 1] : null;
    if (!element) return null;
    return {
      element: element,
      kind: element.tagName === 'DIALOG' ? 'native' : 'aria'
    };
  }

  function omnideckAriaDialogSuppressesBackground(dialogElement) {
    const bodyStyle = document.body ? window.getComputedStyle(document.body) : null;
    const rootStyle = window.getComputedStyle(document.documentElement);
    const locksOverflow = (style) => style
      && (style.overflowY === 'hidden' || style.overflowY === 'clip');
    if (locksOverflow(bodyStyle)
        || locksOverflow(rootStyle)
        || bodyStyle?.position === 'fixed')
      return true;

    let dialogBranch = dialogElement;
    while (dialogBranch.parentElement && dialogBranch.parentElement !== document.body) {
      dialogBranch = dialogBranch.parentElement;
    }

    return Array.from(document.body?.children || []).some((element) => {
      if (element === dialogBranch) return false;
      if (element.hasAttribute('inert')) return true;
      if (element.getAttribute('aria-hidden') !== 'true') return false;

      // aria-hidden is common on decorative icons. Treat it as background
      // suppression only on a substantial top-level application subtree.
      const rect = element.getBoundingClientRect();
      const substantial = rect.width * rect.height >= window.innerWidth * window.innerHeight * 0.25
        || element.scrollHeight > window.innerHeight
        || (element.innerText || '').trim().length > 500;
      return substantial && Boolean(element.querySelector(
        'a[href],button,input,select,textarea,[role="button"],[role="link"]'
      ));
    });
  }

  function omnideckControlLooksLikeClose(el) {
    const metadata = [
      el.id || '',
      typeof el.className === 'string' ? el.className : '',
      el.getAttribute('name') || '',
      el.getAttribute('data-testid') || ''
    ].join(' ').toLowerCase();
    return /(^|[\s_-])(close|dismiss)(?=$|[\s_-])/.test(metadata);
  }

  function omnideckCustomModal() {
    if (!document.body) return null;
    const bodyStyle = window.getComputedStyle(document.body);
    if (bodyStyle.overflowY !== 'hidden' && bodyStyle.overflowY !== 'clip')
      return null;

    const candidates = Array.from(document.body.querySelectorAll('*')).filter((el) => {
      if (!omnideckElementIsVisible(el)) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      if (style.position !== 'fixed' || style.pointerEvents === 'none') return false;
      if (rect.width < window.innerWidth * 0.5
          || rect.height < window.innerHeight * 0.5)
        return false;

      const metadata = [
        el.id || '',
        typeof el.className === 'string' ? el.className : ''
      ].join(' ').toLowerCase();
      const looksLikeModal = /modal|dialog|overlay|backdrop|lightbox|popup|paywall|auth/.test(
        metadata
      );
      const hasCloseControl = Array.from(
        el.querySelectorAll('button,[role="button"],a[href]')
      ).some(omnideckControlLooksLikeClose);
      return looksLikeModal || hasCloseControl;
    });
    if (candidates.length === 0) return null;

    candidates.sort((left, right) => {
      const leftZ = parseInt(window.getComputedStyle(left).zIndex, 10) || 0;
      const rightZ = parseInt(window.getComputedStyle(right).zIndex, 10) || 0;
      return leftZ - rightZ;
    });
    return { element: candidates[candidates.length - 1], kind: 'custom' };
  }

  function omnideckActiveModal() {
    return omnideckSemanticModal() || omnideckCustomModal();
  }

  function omnideckModalControlName(el) {
    if (!omnideckControlLooksLikeClose(el)) return '';
    const metadata = [
      el.id || '',
      typeof el.className === 'string' ? el.className : '',
      el.getAttribute('name') || '',
      el.getAttribute('data-testid') || ''
    ].join(' ').toLowerCase();
    return /(^|[\s_-])dismiss(?=$|[\s_-])/.test(metadata) ? 'Dismiss' : 'Close';
  }

  function omnideckScrollableModalElement(modalElement) {
    if (!modalElement) return null;
    const candidates = [modalElement, ...modalElement.querySelectorAll('*')]
      .filter((el) => {
        if (!omnideckElementIsVisible(el)) return false;
        const style = window.getComputedStyle(el);
        return (style.overflowY === 'auto' || style.overflowY === 'scroll')
          && el.scrollHeight > el.clientHeight + 1;
      });
    if (candidates.length === 0) return null;
    candidates.sort((left, right) => {
      const leftRect = left.getBoundingClientRect();
      const rightRect = right.getBoundingClientRect();
      return (rightRect.width * rightRect.height) - (leftRect.width * leftRect.height);
    });
    return candidates[0];
  }
"""


__all__ = ["MODAL_HELPERS_JS"]
