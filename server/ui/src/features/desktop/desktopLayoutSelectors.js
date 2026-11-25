/** Locate a docked View without exposing tab-group storage details to callers. */
export function tabGroupContainingView(tabGroups, viewId) {
    return Object.entries(tabGroups).find(([, tabGroup]) => (
        tabGroup.viewIds.includes(viewId)
    ))?.[0] || null;
}

/** Apply the shared "next, otherwise previous" selection rule after close. */
export function nextActiveViewIdAfterClose(tabGroup, closingViewId) {
    const index = tabGroup.viewIds.indexOf(closingViewId);
    if (index < 0) return tabGroup.activeViewId;
    const remainingIds = tabGroup.viewIds.filter(
        (viewId) => viewId !== closingViewId,
    );
    return remainingIds[index] || remainingIds[index - 1] || null;
}

/** Tab groups that hold views. */
export function visibleTabGroupIds(model) {
    const left = model.tabGroups.left.viewIds.length > 0;
    const right = model.tabGroups.right.viewIds.length > 0;
    return [left && 'left', right && 'right'].filter(Boolean);
}

/** Derive presentation visibility without treating keyboard focus as visibility. */
export function visibleViewIds(model) {
    if (model.fullscreenViewId) return [model.fullscreenViewId];
    const activeIds = visibleTabGroupIds(model)
        .map((id) => model.tabGroups[id].activeViewId);
    return Object.keys(model.openViewsById).filter((id) => (
        Boolean(model.floatingByViewId[id]) || activeIds.includes(id)
    ));
}
