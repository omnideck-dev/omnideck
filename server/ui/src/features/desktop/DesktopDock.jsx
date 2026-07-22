import CustomAppHost from '../../components/apps/CustomAppHost.jsx';
import CustomAppToolbar, {
    CustomAppDockActions,
    CustomAppError,
} from '../../components/apps/CustomAppToolbar.jsx';
import SplitHandle from '../../components/SplitHandle.jsx';
import TabbedPane from '../../components/TabbedPane.jsx';
import WorkspacePreviewContent from '../workspace/WorkspacePreviewContent.jsx';
import styles from './DesktopDock.module.css';

/** One right-hand dock shared by Custom Apps and workspace previews. */
export default function DesktopDock({
    visible,
    expanded,
    includeCustomApp,
    dock,
    customApps,
    preview,
    browser,
    actions,
}) {
    const items = includeCustomApp
        ? dock.items
        : dock.items.filter((item) => item.kind !== 'custom-app');
    const activeItemId = items.some((item) => item.id === dock.activeItemId)
        ? dock.activeItemId
        : items.at(-1)?.id || null;
    const hasContent = Boolean(customApps.openApp || preview.tabs.length > 0);
    if (!hasContent) return null;

    const testId = expanded && customApps.isHome ? 'home-view' : 'desktop-dock';
    return (
        <>
            {visible && !expanded && <SplitHandle onDrag={dock.setSplitPosition} />}
            <div
                className={`${styles.dock} ${expanded ? styles.expanded : styles.docked} ${!visible ? styles.hidden : ''}`}
                data-testid={testId}
                data-layout={expanded ? 'expanded' : 'docked'}
                data-visible={visible ? 'true' : 'false'}
            >
                {expanded && customApps.openApp && (
                    <CustomAppToolbar
                        app={customApps.openApp}
                        isHome={customApps.isHome}
                        onOpenApps={actions.openCustomApps}
                        onOpenChat={actions.dockCustomApp}
                        onClose={actions.closeCustomApp}
                        onToggleHome={actions.toggleCustomAppHome}
                        onReload={customApps.reload}
                    />
                )}
                <CustomAppError message={customApps.error} />
                <TabbedPane
                    tabs={items}
                    activeTab={activeItemId}
                    onTabChange={dock.selectItem}
                    onCloseTab={actions.closeDockItem}
                    hideTabs={expanded}
                    actions={activeItemId === dock.customAppItemId
                        ? (
                            <CustomAppDockActions
                                onExpand={actions.expandCustomApp}
                                onReload={customApps.reload}
                            />
                        )
                        : null}
                >
                    {customApps.openApp && (
                        <CustomAppHost
                            app={customApps.openApp}
                            reloadSignal={customApps.reloadSignal}
                            active={visible && activeItemId === dock.customAppItemId}
                            onOpenChat={actions.dockCustomApp}
                            onComposeChat={actions.composeFromCustomApp}
                        />
                    )}
                    {visible && (
                        <WorkspacePreviewContent
                            activeTab={activeItemId}
                            preview={preview}
                            browser={browser}
                        />
                    )}
                </TabbedPane>
            </div>
        </>
    );
}
