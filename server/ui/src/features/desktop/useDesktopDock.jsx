import { useCallback, useEffect, useMemo, useState } from 'react';

/** Owns selection and width for the shared Custom App / workspace preview dock. */
export default function useDesktopDock({ customApp, preview }) {
    const customAppItemId = customApp ? `custom-app:${customApp.slug}` : null;
    const [activeItemId, setActiveItemId] = useState(null);
    const [splitPosition, setSplitPosition] = useState(40);

    const items = useMemo(() => [
        ...(customApp ? [{
            id: customAppItemId,
            testid: customAppItemId,
            label: customApp.title,
            icon: <i className={`bi ${customApp.icon}`} />,
            kind: 'custom-app',
        }] : []),
        ...preview.tabs.map((tab) => ({ ...tab, kind: 'workspace-preview' })),
    ], [customApp, customAppItemId, preview.tabs]);

    const selectItem = useCallback((itemId) => {
        setActiveItemId(itemId);
        if (itemId !== customAppItemId) preview.setActiveTab(itemId);
    }, [customAppItemId, preview.setActiveTab]);

    const showCustomApp = useCallback((slug = customApp?.slug) => {
        if (slug) setActiveItemId(`custom-app:${slug}`);
    }, [customApp?.slug]);

    const showWorkspacePreview = useCallback((itemId) => {
        preview.setActiveTab(itemId);
        setActiveItemId(itemId);
    }, [preview.setActiveTab]);

    useEffect(() => {
        if (!activeItemId) {
            setActiveItemId(customAppItemId || preview.activeTab);
            return;
        }
        if (activeItemId === customAppItemId) return;
        if (preview.tabs.some((tab) => tab.id === activeItemId)) return;
        setActiveItemId(preview.activeTab || customAppItemId);
    }, [activeItemId, customAppItemId, preview.activeTab, preview.tabs]);

    useEffect(() => {
        if (customAppItemId || !preview.activeTab) return;
        setActiveItemId(preview.activeTab);
    }, [customAppItemId, preview.activeTab]);

    return {
        items,
        activeItemId,
        customAppItemId,
        splitPosition,
        setSplitPosition,
        selectItem,
        showCustomApp,
        showWorkspacePreview,
    };
}
