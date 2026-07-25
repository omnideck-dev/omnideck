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

/** Return each tab group once, with the focused group first. */
export function focusOrderedTabGroupIds(model) {
    return [
        model.focusedTabGroupId,
        ...Object.keys(model.tabGroups),
    ].filter((tabGroupId, index, all) => (
        tabGroupId && all.indexOf(tabGroupId) === index
    ));
}

/**
 * Visible Views ordered as a user would expect focus to fall back:
 * top-most floating Views, then active docked Views by tab-group focus.
 */
export function focusOrderedVisibleViews(model, excludingViewId = null) {
    const floatingViews = [...(model.floatingViews || [])]
        .filter((floatingView) => floatingView.viewId !== excludingViewId)
        .sort((left, right) => right.zIndex - left.zIndex)
        .map((floatingView) => model.openViewsById[floatingView.viewId]);
    const dockedViews = focusOrderedTabGroupIds(model)
        .map((tabGroupId) => {
            const activeViewId = model.tabGroups[tabGroupId].activeViewId;
            return model.openViewsById[activeViewId];
        });
    return [...floatingViews, ...dockedViews].filter(Boolean);
}
