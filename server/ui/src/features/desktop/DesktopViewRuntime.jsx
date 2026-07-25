import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useRef,
} from 'react';

import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';
import { tabGroupContainingView } from './desktopLayoutSelectors.js';
import { CONVERSATION_VIEW_ID } from './desktopViews.js';

const DesktopViewCatalogContext = createContext(null);
const DesktopViewCommandsContext = createContext(null);

/** Return the tab group opposite Conversation, falling back to the right. */
export function preferredCompanionTabGroup(model) {
    const conversationView = model.openViewsById[CONVERSATION_VIEW_ID];
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
                {children}
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
