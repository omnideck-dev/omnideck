import PreviewPanel from './PreviewPanel.jsx';
import styles from './WorkspacePane.module.css';

/** Generic full/split shell workspace over a tabbed PreviewPanel. */
export default function WorkspacePane({
    visible,
    layout,
    testId = 'workspace-pane',
    toolbar = null,
    banner = null,
    tabs,
    activeTab,
    onTabChange,
    onCloseTab,
    tabActions = null,
    children,
}) {
    const isFull = visible && layout === 'full';
    return (
        <div
            className={`${styles.workspace} ${isFull ? styles.full : styles.split} ${!visible ? styles.hidden : ''}`}
            data-testid={testId}
            data-layout={layout}
            data-visible={visible ? 'true' : 'false'}
        >
            {isFull && toolbar}
            {banner}
            <PreviewPanel
                tabs={tabs}
                activeTab={activeTab}
                onTabChange={onTabChange}
                onCloseTab={onCloseTab}
                hideTabs={!visible || layout !== 'split'}
                actions={tabActions}
            >
                {children}
            </PreviewPanel>
        </div>
    );
}
