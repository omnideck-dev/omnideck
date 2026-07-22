import CustomAppHost from '../../components/apps/CustomAppHost.jsx';
import CustomAppLayout from '../../components/CustomAppLayout.jsx';
import CustomAppToolbar, {
    CustomAppError,
    CustomAppReloadAction,
} from '../../components/apps/CustomAppToolbar.jsx';
import SplitHandle from '../../components/SplitHandle.jsx';
import TabbedPane from '../../components/TabbedPane.jsx';
import WorkspacePreviewContent from '../workspace/WorkspacePreviewContent.jsx';

export default function PersistentCustomAppLayer({ customApps, visible, preview, browser }) {
    if (!customApps.app) return null;
    return (
        <>
            {visible && customApps.layout === 'split' && (
                <SplitHandle onDrag={preview.setSplitPosition} />
            )}
            <CustomAppLayout
                visible={visible}
                layout={customApps.layout}
                testId={customApps.origin === 'home' ? 'home-view' : 'custom-app-workspace'}
                toolbar={(
                    <CustomAppToolbar
                        app={customApps.app}
                        origin={customApps.origin}
                        isHome={customApps.isHome}
                        onOpenApps={customApps.openApps}
                        onOpenChat={customApps.openChat}
                        onToggleHome={customApps.toggleHome}
                        onReload={customApps.reload}
                    />
                )}
                banner={<CustomAppError message={customApps.error} />}
            >
                <TabbedPane
                    tabs={customApps.tabs}
                    activeTab={customApps.activeTab}
                    onTabChange={customApps.selectTab}
                    onCloseTab={customApps.closeTab}
                    hideTabs={!visible || customApps.layout !== 'split'}
                    actions={customApps.activeTab === customApps.appTabId
                        ? <CustomAppReloadAction onReload={customApps.reload} />
                        : null}
                >
                    <CustomAppHost
                        app={customApps.app}
                        reloadSignal={customApps.reloadSignal}
                        active={customApps.activeTab === customApps.appTabId}
                        onOpenChat={customApps.openChat}
                        onComposeChat={customApps.composeInChat}
                    />
                    <WorkspacePreviewContent
                        activeTab={customApps.activeTab}
                        preview={preview}
                        browser={browser}
                    />
                </TabbedPane>
            </CustomAppLayout>
        </>
    );
}
