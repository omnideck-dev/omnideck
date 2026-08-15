"""Shared browser-side detection for active interaction surfaces."""

from __future__ import annotations

# Keep this as plain JavaScript function declarations so it can be embedded in
# both the renderer's one-round-trip DOM walk and scrolling's state checks.
#
# A modal is defined by unavailable background interaction, not by whether the
# document happens to scroll. Native top-layer state and explicit background
# suppression are authoritative. Custom surfaces are detected by hit-testing a
# large viewport layer that actually sits in front of otherwise actionable page
# content. ARIA is useful supporting evidence, but is not trusted on its own.
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

  function omnideckElementHasRenderedBox(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    if (!(rect.bottom > 0
      && rect.top < window.innerHeight
      && rect.right > 0
      && rect.left < window.innerWidth
      && rect.width > 0
      && rect.height > 0))
      return false;

    for (let current = element; current; current = omnideckComposedParent(current)) {
      const style = window.getComputedStyle(current);
      if (style.display === 'none'
          || style.visibility === 'hidden'
          || style.visibility === 'collapse')
        return false;
    }
    return true;
  }

  function omnideckElementIsVisible(element) {
    if (!omnideckElementHasRenderedBox(element)) return false;
    for (let current = element; current; current = omnideckComposedParent(current)) {
      if (parseFloat(window.getComputedStyle(current).opacity || '1') <= 0) return false;
    }
    return true;
  }

  function omnideckViewportCoverage(element) {
    const rect = element.getBoundingClientRect();
    const width = Math.max(
      0,
      Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0)
    );
    const height = Math.max(
      0,
      Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0)
    );
    const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
    return (width * height) / viewportArea;
  }

  function omnideckElementsFromPoint(x, y) {
    const elements = [];
    const visitedRoots = new Set();
    let root = document;
    while (root
        && typeof root.elementsFromPoint === 'function'
        && !visitedRoots.has(root)) {
      visitedRoots.add(root);
      const hits = root.elementsFromPoint(x, y);
      for (const hit of hits) {
        if (!elements.includes(hit)) elements.push(hit);
      }
      const shadowHost = hits.find((hit) => hit.shadowRoot);
      root = shadowHost?.shadowRoot || null;
    }
    return elements;
  }

  function omnideckTopElementFromPoint(x, y) {
    let root = document;
    let top = null;
    const visitedRoots = new Set();
    while (root
        && typeof root.elementFromPoint === 'function'
        && !visitedRoots.has(root)) {
      visitedRoots.add(root);
      const hit = root.elementFromPoint(x, y);
      if (!hit) break;
      top = hit;
      root = hit.shadowRoot || null;
    }
    return top;
  }

  function omnideckPointerSampleCount(element) {
    const samples = [
      [0.1, 0.1], [0.5, 0.1], [0.9, 0.1],
      [0.1, 0.5], [0.5, 0.5], [0.9, 0.5],
      [0.1, 0.9], [0.5, 0.9], [0.9, 0.9]
    ];
    return samples.filter(([xRatio, yRatio]) => {
      const hit = omnideckTopElementFromPoint(
        window.innerWidth * xRatio,
        window.innerHeight * yRatio
      );
      return hit && omnideckComposedContains(element, hit);
    }).length;
  }

  function omnideckIsViewportPointerBlocker(element) {
    // Opacity does not affect hit-testing: a transparent click catcher still
    // prevents physical input from reaching the page underneath it.
    if (!omnideckElementHasRenderedBox(element)) return false;
    const style = window.getComputedStyle(element);
    if (style.pointerEvents === 'none') return false;
    if (style.position !== 'fixed' && style.position !== 'absolute') return false;
    if (omnideckViewportCoverage(element) < 0.85) return false;
    return omnideckPointerSampleCount(element) >= 6;
  }

  function omnideckPointerBlockerFor(element) {
    const blockers = [];
    for (let current = element; current; current = omnideckComposedParent(current)) {
      if (omnideckIsViewportPointerBlocker(current)) blockers.push(current);
    }
    blockers.sort((left, right) => {
      return omnideckViewportCoverage(right) - omnideckViewportCoverage(left);
    });
    return blockers[0] || null;
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

  function omnideckHasActionableContent(element) {
    return [element, ...omnideckElementsIn(element)].some((descendant) => {
      return descendant.matches(
        'a[href],button,input,select,textarea,[role="button"],[role="link"]'
      ) && omnideckElementIsVisible(descendant);
    });
  }

  function omnideckBranchIsSuppressed(element) {
    const rect = element.getBoundingClientRect();
    const isSubstantial = omnideckElementIsVisible(element)
      && (rect.width * rect.height >= window.innerWidth * window.innerHeight * 0.25
        || element.scrollHeight > window.innerHeight);
    const isMeaningfulBackground = omnideckHasActionableContent(element) || isSubstantial;

    if (element.hasAttribute('inert')) return isMeaningfulBackground;
    if (element.getAttribute('aria-hidden') === 'true') return isMeaningfulBackground;

    return omnideckElementsIn(element).filter((descendant) => {
      return descendant.hasAttribute('inert')
        || descendant.getAttribute('aria-hidden') === 'true';
    }).some((suppressedElement) => {
      const suppressedRect = suppressedElement.getBoundingClientRect();
      return omnideckElementIsVisible(suppressedElement)
        && (suppressedRect.width * suppressedRect.height
            >= window.innerWidth * window.innerHeight * 0.25
          || suppressedElement.scrollHeight > window.innerHeight
          || omnideckHasActionableContent(suppressedElement));
    });
  }

  function omnideckDialogSuppressesBackground(dialogElement) {
    return omnideckBackgroundBranches(dialogElement).some(omnideckBranchIsSuppressed);
  }

  function omnideckNativeModal(element) {
    if (element.tagName !== 'DIALOG') return false;
    try {
      return element.matches(':modal');
    } catch (_error) {
      return false;
    }
  }

  function omnideckSemanticModal() {
    const candidates = omnideckQueryAll(
      'dialog,[role="dialog"],[role="alertdialog"]'
    ).filter((element) => omnideckElementIsVisible(element));
    const active = candidates.flatMap((element) => {
      if (omnideckNativeModal(element)) {
        return [{ element: element, elements: [element], kind: 'native' }];
      }

      const backgroundSuppressed = omnideckDialogSuppressesBackground(element);
      const pointerBlocker = omnideckPointerBlockerFor(element);
      const ariaModal = element.getAttribute('aria-modal') === 'true';
      if (!backgroundSuppressed && !(pointerBlocker && ariaModal)) return [];

      return [{
        element: element,
        elements: pointerBlocker ? [pointerBlocker] : [element],
        kind: backgroundSuppressed ? 'semantic' : 'pointer'
      }];
    });

    const focusedElement = omnideckDeepActiveElement();
    const focused = active.find((modal) => {
      return focusedElement && omnideckComposedContains(modal.element, focusedElement);
    });
    return focused || (active.length > 0 ? active[active.length - 1] : null);
  }

  function omnideckControlLooksLikeClose(element) {
    const metadata = [
      element.id || '',
      typeof element.className === 'string' ? element.className : '',
      element.getAttribute('name') || '',
      element.getAttribute('data-testid') || ''
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

  function omnideckElementIsBehind(blocker, element) {
    const rect = element.getBoundingClientRect();
    const x = Math.max(0, Math.min(window.innerWidth - 1, rect.left + rect.width / 2));
    const y = Math.max(0, Math.min(window.innerHeight - 1, rect.top + rect.height / 2));
    const hits = omnideckElementsFromPoint(x, y);
    const blockerIndex = hits.findIndex((hit) => {
      return omnideckComposedContains(blocker, hit);
    });
    const elementIndex = hits.findIndex((hit) => {
      return hit === element || omnideckComposedContains(element, hit);
    });
    return blockerIndex >= 0 && (elementIndex < 0 || blockerIndex < elementIndex);
  }

  function omnideckBlockerCoversBackground(blocker) {
    return omnideckElementsIn(document.body).some((element) => {
      if (omnideckComposedContains(blocker, element)) return false;
      if (!omnideckElementIsVisible(element)) return false;
      const actionable = element.matches(
        'a[href],button,input,select,textarea,[role="button"],[role="link"]'
      );
      const rect = element.getBoundingClientRect();
      const substantial = rect.width * rect.height
          >= window.innerWidth * window.innerHeight * 0.25
        || element.scrollHeight > window.innerHeight;
      return (actionable || substantial) && omnideckElementIsBehind(blocker, element);
    });
  }

  function omnideckSurfaceRootsForBlocker(blocker) {
    const roots = [blocker];
    const blockerStyle = window.getComputedStyle(blocker);
    const blockerZ = parseInt(blockerStyle.zIndex, 10) || 0;
    const blockerRect = blocker.getBoundingClientRect();

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
      const rect = element.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      if (centerX < blockerRect.left || centerX > blockerRect.right
          || centerY < blockerRect.top || centerY > blockerRect.bottom)
        continue;

      const role = element.getAttribute('role');
      const looksLikeSurface = role === 'dialog'
        || role === 'alertdialog'
        || omnideckHasActionableContent(element)
        || omnideckElementsIn(element).some((descendant) => descendant.tagName === 'IFRAME');
      if (!looksLikeSurface) continue;

      if (!roots.some((root) => omnideckComposedContains(root, element))) roots.push(element);
    }
    return roots;
  }

  function omnideckCustomModal() {
    if (!document.body) return null;
    const blockers = omnideckElementsIn(document.body).filter((element) => {
      return omnideckIsViewportPointerBlocker(element)
        && omnideckBlockerCoversBackground(element);
    });
    if (blockers.length === 0) return null;

    blockers.sort((left, right) => {
      const leftZ = parseInt(window.getComputedStyle(left).zIndex, 10) || 0;
      const rightZ = parseInt(window.getComputedStyle(right).zIndex, 10) || 0;
      if (leftZ !== rightZ) return leftZ - rightZ;
      return omnideckViewportCoverage(left) - omnideckViewportCoverage(right);
    });
    const blocker = blockers[blockers.length - 1];
    const roots = omnideckSurfaceRootsForBlocker(blocker);
    return {
      element: roots[roots.length - 1],
      elements: roots,
      kind: 'pointer'
    };
  }

  function omnideckActiveModal() {
    return omnideckSemanticModal() || omnideckCustomModal();
  }

  function omnideckModalControlName(element) {
    if (!omnideckControlLooksLikeClose(element)) return '';
    const metadata = [
      element.id || '',
      typeof element.className === 'string' ? element.className : '',
      element.getAttribute('name') || '',
      element.getAttribute('data-testid') || ''
    ].join(' ').toLowerCase();
    return /(^|[\s_-])dismiss(?=$|[\s_-])/.test(metadata) ? 'Dismiss' : 'Close';
  }

  function omnideckScrollableModalElement(modal) {
    const roots = omnideckModalElements(modal);
    if (roots.length === 0) return null;
    const candidates = roots.flatMap((root) => [root, ...omnideckElementsIn(root)])
      .filter((element) => {
        if (!omnideckElementIsVisible(element)) return false;
        const style = window.getComputedStyle(element);
        return (style.overflowY === 'auto' || style.overflowY === 'scroll')
          && element.scrollHeight > element.clientHeight + 1;
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
