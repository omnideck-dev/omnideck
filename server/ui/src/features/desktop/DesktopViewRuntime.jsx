import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useRef,
} from 'react';

import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';
import { tabGroupContainingView } from './desktopLayoutSelectors.js';

const DesktopViewCatalogContext = createContext(null);
const DesktopViewCommandsContext = createContext(null);
const DesktopViewFocusContext = createContext(null);

/** Return the tab group opposite Conversation, falling back to the right. */
function preferredCompanionTabGroup(model) {
    const conversationView = Object.values(model.openViewsById).find(
        (view) => view.type === 'conversation',
    );
    const conversationTabGroupId = conversationView
        ? tabGroupContainingView(model.tabGroups, conversationView.id)
        : null;
    return conversationTabGroupId === DESKTOP_TAB_GROUP_IDS.RIGHT
        ? DESKTOP_TAB_GROUP_IDS.LEFT
        : DESKTOP_TAB_GROUP_IDS.RIGHT;
}

/**
 * Exposes Desktop state and generic View commands to domain adapters.
 *
 * Domain adapters translate their own resources into serializable Views, then
 * cross this boundary with View and placement concepts only.
 */
export function DesktopViewRuntimeProvider({ desktopLayout, children }) {
    const { model, commands: layoutCommands } = desktopLayout;
    const modelRef = useRef(model);
    modelRef.current = model;
    // Bounds, split ratios, and focus change frequently. Domain effects need
    // only the View catalog, so keep their context value stable for pure
    // placement updates.
    const viewCatalog = useMemo(() => ({
        openViews: Object.values(model.openViewsById),
        openViewsById: model.openViewsById,
    }), [model.openViewsById]);
    const focusedTabGroupActiveViewId = model.tabGroups[
        model.focusedTabGroupId
    ]?.activeViewId || null;
    // Focus is intentionally a separate subscription from the View catalog.
    // Tab selection and floating-window focus change often, while domain
    // lifecycle effects only need to wake when the catalog itself changes.
    const viewFocus = useMemo(() => ({
        focusedViewId: model.focusedFloatingViewId
            || focusedTabGroupActiveViewId,
    }), [
        model.focusedFloatingViewId,
        model.focusedTabGroupId,
        focusedTabGroupActiveViewId,
    ]);

    const openView = useCallback((view, {
        tabGroupId = DESKTOP_TAB_GROUP_IDS.LEFT,
        activate = true,
    } = {}) => {
        layoutCommands.openView(view, tabGroupId, { activate });
    }, [layoutCommands.openView]);

    // These mutations remain generic: callers supply View descriptions or IDs,
    // never artifacts, agents, conversations, or Custom App objects.
    const updateViews = useCallback(
        (views) => layoutCommands.updateViews(views),
        [layoutCommands.updateViews],
    );
    const syncViews = useCallback(
        (changes) => layoutCommands.syncViews(changes),
        [layoutCommands.syncViews],
    );
    const closeView = useCallback(
        (viewId) => layoutCommands.closeView(viewId),
        [layoutCommands.closeView],
    );
    const closeViews = useCallback(
        (viewIds) => layoutCommands.closeViews(viewIds),
        [layoutCommands.closeViews],
    );

    // Placement callers need the latest model, but they should receive stable
    // commands. In particular, navigation effects must not restart merely
    // because a drag or tab selection produced a new layout object.
    const preferredTabGroupId = useCallback(
        () => preferredCompanionTabGroup(modelRef.current),
        [],
    );

    const commands = useMemo(() => ({
        openView,
        updateViews,
        syncViews,
        closeView,
        closeViews,
        preferredTabGroupId,
    }), [
        closeView,
        closeViews,
        openView,
        preferredTabGroupId,
        syncViews,
        updateViews,
    ]);

    return (
        <DesktopViewCatalogContext.Provider value={viewCatalog}>
            <DesktopViewCommandsContext.Provider value={commands}>
                <DesktopViewFocusContext.Provider value={viewFocus}>
                    {children}
                </DesktopViewFocusContext.Provider>
            </DesktopViewCommandsContext.Provider>
        </DesktopViewCatalogContext.Provider>
    );
}

export function useDesktopViewCatalog() {
    const catalog = useContext(DesktopViewCatalogContext);
    if (catalog === null) {
        throw new Error(
            'useDesktopViewCatalog must be used within DesktopViewRuntimeProvider',
        );
    }
    return catalog;
}

export function useDesktopViewCommands() {
    const commands = useContext(DesktopViewCommandsContext);
    if (commands === null) {
        throw new Error(
            'useDesktopViewCommands must be used within DesktopViewRuntimeProvider',
        );
    }
    return commands;
}

/**
 * Return the one View which owns keyboard/control focus in Desktop Layout.
 *
 * Visibility is deliberately broader than focus: both tab groups and every
 * floating View may be visible, but exclusive domain side channels need one
 * unambiguous owner.
 */
export function useFocusedViewId() {
    const focus = useContext(DesktopViewFocusContext);
    if (focus === null) {
        throw new Error(
            'useFocusedViewId must be used within DesktopViewRuntimeProvider',
        );
    }
    return focus.focusedViewId;
}
