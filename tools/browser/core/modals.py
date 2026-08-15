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
  function omnideckElementsIn(root) {
    const elements = Array.from(root.querySelectorAll('*'));
    for (const element of [...elements]) {
      if (element.shadowRoot) elements.push(...omnideckElementsIn(element.shadowRoot));
    }
    return elements;
  }

  function omnideckQueryAll(selector) {
    return omnideckElementsIn(document).filter((element) => element.matches(selector));
  }

  function omnideckComposedParent(element) {
    if (element.parentElement) return element.parentElement;
    const root = element.getRootNode();
    return root instanceof ShadowRoot ? root.host : null;
  }

  function omnideckComposedContains(root, element) {
    for (let current = element; current; current = omnideckComposedParent(current)) {
      if (current === root) return true;
    }
    return false;
  }

  function omnideckDeepActiveElement() {
    let active = document.activeElement;
    while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
    return active;
  }

  function omnideckElementIsVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (!(rect.bottom > 0
      && rect.top < window.innerHeight
      && rect.right > 0
      && rect.left < window.innerWidth
      && rect.width > 0
      && rect.height > 0))
      return false;

    for (let current = el; current; current = omnideckComposedParent(current)) {
      const style = window.getComputedStyle(current);
      if (style.display === 'none'
          || style.visibility === 'hidden'
          || style.visibility === 'collapse'
          || parseFloat(style.opacity || '1') <= 0)
        return false;
    }
    return true;
  }

  function omnideckSemanticModal() {
    let candidates = [];
    try {
      candidates = omnideckQueryAll(
        'dialog:modal,'
        + '[role="dialog"][aria-modal="true"],'
        + '[role="alertdialog"][aria-modal="true"]'
      );
    } catch (_error) {
      candidates = omnideckQueryAll(
        '[role="dialog"][aria-modal="true"],'
        + '[role="alertdialog"][aria-modal="true"]'
      );
    }
    candidates = candidates.filter((element) => {
      if (!omnideckElementIsVisible(element)) return false;
      if (element.tagName === 'DIALOG') return true;
      return omnideckAriaDialogSuppressesBackground(element);
    });
    const focusedElement = omnideckDeepActiveElement();
    const focused = candidates.find((element) => {
      return focusedElement && omnideckComposedContains(element, focusedElement);
    });
    const element = focused || (candidates.length > 0 ? candidates[candidates.length - 1] : null);
    if (!element) return null;
    return {
      element: element,
      kind: element.tagName === 'DIALOG' ? 'native' : 'aria'
    };
  }

  function omnideckBackgroundBranches(dialogElement) {
    const branches = [];
    let dialogBranch = dialogElement;
    while (dialogBranch && dialogBranch !== document.body) {
      const root = dialogBranch.getRootNode();
      const container = dialogBranch.parentElement
        || (root instanceof ShadowRoot ? root : null);
      if (!container) break;
      for (const sibling of container.children) {
        if (sibling !== dialogBranch) branches.push(sibling);
      }
      dialogBranch = container instanceof ShadowRoot ? container.host : container;
    }
    return branches;
  }

  function omnideckBranchIsSuppressed(element) {
    const branchElements = [element, ...omnideckElementsIn(element)];
    const hasActionableContent = branchElements.some((descendant) => {
      return descendant.matches(
        'a[href],button,input,select,textarea,[role="button"],[role="link"]'
      ) && omnideckElementIsVisible(descendant);
    });
    const rect = element.getBoundingClientRect();
    const isSubstantial = omnideckElementIsVisible(element)
      && (rect.width * rect.height >= window.innerWidth * window.innerHeight * 0.25
        || element.scrollHeight > window.innerHeight);
    const isMeaningfulBackground = hasActionableContent || isSubstantial;

    if (element.hasAttribute('inert')) return isMeaningfulBackground;
    if (element.getAttribute('aria-hidden') === 'true') return isMeaningfulBackground;

    return omnideckElementsIn(element).filter((descendant) => {
      return descendant.hasAttribute('inert');
    }).some((inertElement) => {
      const rect = inertElement.getBoundingClientRect();
      return omnideckElementIsVisible(inertElement)
        && (rect.width * rect.height >= window.innerWidth * window.innerHeight * 0.25
          || inertElement.scrollHeight > window.innerHeight
          || [inertElement, ...omnideckElementsIn(inertElement)].some((descendant) => {
            return descendant.matches(
              'a[href],button,input,select,textarea,[role="button"],[role="link"]'
            ) && omnideckElementIsVisible(descendant);
          }));
    });
  }

  function omnideckBackgroundCanScroll(dialogElement) {
    return omnideckBackgroundBranches(dialogElement).some((branch) => {
      return [branch, ...omnideckElementsIn(branch)].some((element) => {
        if (!omnideckElementIsVisible(element)) return false;
        const style = window.getComputedStyle(element);
        return (style.overflowY === 'auto' || style.overflowY === 'scroll')
          && element.scrollHeight > element.clientHeight + 1;
      });
    });
  }

  function omnideckAriaDialogSuppressesBackground(dialogElement) {
    const backgroundBranches = omnideckBackgroundBranches(dialogElement);
    if (backgroundBranches.some(omnideckBranchIsSuppressed)) return true;

    const bodyStyle = document.body ? window.getComputedStyle(document.body) : null;
    const rootStyle = window.getComputedStyle(document.documentElement);
    const locksOverflow = (style) => style
      && (style.overflowY === 'hidden' || style.overflowY === 'clip');
    const documentLocked = locksOverflow(bodyStyle)
        || locksOverflow(rootStyle)
        || bodyStyle?.position === 'fixed';
    return documentLocked && !omnideckBackgroundCanScroll(dialogElement);
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

  function omnideckModalElements(modal) {
    if (!modal) return [];
    return Array.isArray(modal.elements) ? modal.elements : [modal.element];
  }

  function omnideckModalContains(modal, element) {
    return omnideckModalElements(modal).some((root) => {
      return omnideckComposedContains(root, element);
    });
  }

  function omnideckCustomModal() {
    if (!document.body) return null;
    const bodyStyle = window.getComputedStyle(document.body);
    if (bodyStyle.overflowY !== 'hidden' && bodyStyle.overflowY !== 'clip')
      return null;

    const candidates = omnideckElementsIn(document.body).filter((el) => {
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
    const blocker = candidates[candidates.length - 1];
    const blockerZ = parseInt(window.getComputedStyle(blocker).zIndex, 10) || 0;
    const roots = [blocker];

    for (const element of omnideckElementsIn(document.body)) {
      if (element === blocker
          || omnideckComposedContains(blocker, element)
          || omnideckComposedContains(element, blocker))
        continue;
      if (!omnideckElementIsVisible(element)) continue;
      const style = window.getComputedStyle(element);
      if (style.position !== 'fixed' && style.position !== 'absolute') continue;
      const zIndex = parseInt(style.zIndex, 10) || 0;
      if (zIndex < blockerZ) continue;

      const metadata = [
        element.id || '',
        typeof element.className === 'string' ? element.className : ''
      ].join(' ').toLowerCase();
      const role = element.getAttribute('role');
      const looksLikeSurface = role === 'dialog'
        || role === 'alertdialog'
        || /modal|dialog|lightbox|popup|paywall/.test(metadata)
        || omnideckElementsIn(element)
          .filter((descendant) => descendant.matches('button,[role="button"],a[href]'))
          .some(omnideckControlLooksLikeClose)
        || omnideckElementsIn(element).some((descendant) => descendant.tagName === 'IFRAME');
      if (!looksLikeSurface) continue;

      if (!roots.some((root) => omnideckComposedContains(root, element))) roots.push(element);
    }

    return {
      element: roots[roots.length - 1],
      elements: roots,
      kind: 'custom'
    };
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

  function omnideckScrollableModalElement(modal) {
    const roots = omnideckModalElements(modal);
    if (roots.length === 0) return null;
    const candidates = roots.flatMap((root) => [root, ...omnideckElementsIn(root)])
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
