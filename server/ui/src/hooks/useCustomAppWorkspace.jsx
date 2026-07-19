import { useCallback, useEffect, useMemo, useReducer } from 'react';

const INITIAL_STATE = {
    session: null,
    reloadSignal: 0,
    error: '',
};

function reducer(state, action) {
    switch (action.type) {
        case 'OPEN':
            return {
                session: {
                    app: action.app,
                    layout: action.layout,
                    origin: action.origin,
                    activeTab: `app:${action.app.slug}`,
                },
                // Moving the same app between Home, full-space, and split view
                // must not replace its iframe or discard in-page state.
                reloadSignal: state.session?.app.slug === action.app.slug
                    ? state.reloadSignal
                    : 0,
                error: '',
            };
        case 'PRESENT':
            return state.session ? {
                ...state,
                session: {
                    ...state.session,
                    layout: action.layout ?? state.session.layout,
                    activeTab: action.activeTab ?? state.session.activeTab,
                },
            } : state;
        case 'SELECT_TAB':
            return state.session ? {
                ...state,
                session: { ...state.session, activeTab: action.tabId },
            } : state;
        case 'SET_ORIGIN':
            return state.session ? {
                ...state,
                session: { ...state.session, origin: action.origin },
            } : state;
        case 'RELOAD':
            return { ...state, reloadSignal: state.reloadSignal + 1 };
        case 'ERROR':
            return { ...state, error: action.message };
        case 'CLOSE':
            return INITIAL_STATE;
        default:
            return state;
    }
}

/**
 * Keeps one user-opened Custom App mounted across shell navigation until
 * it is closed or replaced, and combines it with conversation preview tabs.
 */
export default function useCustomAppWorkspace({
    preview,
    setDraft,
    setView,
    homeAppSlug,
    onHomeAppChange,
}) {
    const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
    const session = state.session;
    const app = session?.app || null;
    const appTabId = app ? `app:${app.slug}` : null;
    const {
        tabs: previewTabs,
        setActiveTab: setActivePreviewTab,
        closeTab: closePreviewTab,
        openFile: openPreviewFile,
    } = preview;

    const open = useCallback((nextApp, layout, origin) => {
        dispatch({ type: 'OPEN', app: nextApp, layout, origin });
        setView('workspace');
    }, [setView]);

    const openFull = useCallback((nextApp) => open(nextApp, 'full', 'apps'), [open]);
    const openBesideChat = useCallback((nextApp) => open(nextApp, 'split', 'apps'), [open]);
    const openHome = useCallback((nextApp) => open(nextApp, 'full', 'home'), [open]);
    const openApps = useCallback(() => setView('apps'), [setView]);

    const showChat = useCallback((focusApp = false) => {
        if (!session) {
            setView('chat');
            return;
        }
        dispatch({
            type: 'PRESENT',
            layout: 'split',
            activeTab: focusApp ? appTabId : session.activeTab,
        });
        setView('workspace');
    }, [appTabId, session, setView]);

    const openChat = useCallback(() => showChat(true), [showChat]);
    const restoreChat = useCallback(() => showChat(false), [showChat]);

    const close = useCallback(() => {
        dispatch({ type: 'CLOSE' });
        setView('chat');
    }, [setView]);

    const reset = useCallback(() => dispatch({ type: 'CLOSE' }), []);

    const selectTab = useCallback((tabId) => {
        if (!session) return;
        dispatch({ type: 'SELECT_TAB', tabId });
        if (tabId !== appTabId) setActivePreviewTab(tabId);
    }, [appTabId, session, setActivePreviewTab]);

    const closeTab = useCallback((tabId) => {
        if (!session) return;
        if (tabId === appTabId) {
            close();
            return;
        }
        const remaining = previewTabs.filter((tab) => tab.id !== tabId);
        closePreviewTab(tabId);
        if (session.activeTab === tabId) {
            dispatch({
                type: 'SELECT_TAB',
                tabId: remaining.length > 0 ? remaining[remaining.length - 1].id : appTabId,
            });
        }
    }, [appTabId, close, closePreviewTab, previewTabs, session]);

    useEffect(() => {
        if (!session || session.activeTab === appTabId) return;
        if (!previewTabs.some((tab) => tab.id === session.activeTab)) {
            dispatch({ type: 'SELECT_TAB', tabId: appTabId });
        }
    }, [appTabId, previewTabs, session]);

    useEffect(() => {
        if (!homeAppSlug && session?.origin === 'home') {
            dispatch({ type: 'SET_ORIGIN', origin: 'apps' });
        }
    }, [homeAppSlug, session?.origin]);

    const composeInChat = useCallback(({ text, context }) => {
        if (!app) return;
        let addition = text.trim();
        if (context !== null && context !== undefined) {
            try {
                const serialized = JSON.stringify(context, null, 2).slice(0, 12000);
                addition += `${addition ? '\n\n' : ''}Context from ${app.title}:\n${serialized}`;
            } catch {
                // Keep the authored text if the optional context cannot be serialized.
            }
        }
        if (addition) {
            setDraft((current) => current.trim() ? `${current}\n\n${addition}` : addition);
        }
        openChat();
    }, [app, openChat, setDraft]);

    const openPreview = useCallback((item) => {
        openPreviewFile(item);
        if (!session) return;
        dispatch({
            type: 'PRESENT',
            layout: 'split',
            activeTab: `file:${item.path || item.filename}`,
        });
        setView('workspace');
    }, [openPreviewFile, session, setView]);

    const reload = useCallback(() => dispatch({ type: 'RELOAD' }), []);

    const toggleHome = useCallback(async () => {
        if (!session) return;
        dispatch({ type: 'ERROR', message: '' });
        const isHome = session.app.slug === homeAppSlug;
        try {
            const response = await fetch('/api/custom-apps/home', isHome
                ? { method: 'DELETE' }
                : {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ slug: session.app.slug }),
                });
            const body = await response.json();
            if (!response.ok) throw new Error(body.error?.message || 'Could not update Home app');
            const nextHomeSlug = body.home_app_slug || null;
            onHomeAppChange(nextHomeSlug);
            if (session.origin === 'home' && !nextHomeSlug) {
                dispatch({ type: 'SET_ORIGIN', origin: 'apps' });
                openApps();
            }
        } catch (error) {
            dispatch({ type: 'ERROR', message: error.message || 'Could not update Home app' });
        }
    }, [homeAppSlug, onHomeAppChange, openApps, session]);

    const clearUnavailableHome = useCallback(async () => {
        dispatch({ type: 'ERROR', message: '' });
        try {
            const response = await fetch('/api/custom-apps/home', { method: 'DELETE' });
            const body = await response.json();
            if (!response.ok) throw new Error(body.error?.message || 'Could not remove Home app');
            onHomeAppChange(null);
            dispatch({ type: 'SET_ORIGIN', origin: 'apps' });
            openApps();
        } catch (error) {
            dispatch({ type: 'ERROR', message: error.message || 'Could not remove Home app' });
        }
    }, [onHomeAppChange, openApps]);

    const tabs = useMemo(() => app ? [
        {
            id: appTabId,
            testid: appTabId,
            label: app.title,
            icon: <i className={`bi ${app.icon}`} />,
        },
        ...previewTabs,
    ] : [], [app, appTabId, previewTabs]);

    return {
        app,
        appTabId,
        layout: session?.layout || 'full',
        origin: session?.origin || 'apps',
        activeTab: session?.activeTab || null,
        tabs,
        reloadSignal: state.reloadSignal,
        error: state.error,
        isOpen: Boolean(session),
        isHome: Boolean(app && app.slug === homeAppSlug),
        openFull,
        openBesideChat,
        openHome,
        openApps,
        openChat,
        restoreChat,
        composeInChat,
        openPreview,
        selectTab,
        closeTab,
        close,
        reset,
        reload,
        toggleHome,
        clearUnavailableHome,
    };
}
