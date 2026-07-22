import SplitHandle from '../../components/SplitHandle.jsx';
import TabbedPane from '../../components/TabbedPane.jsx';
import styles from '../../App.module.css';
import WorkspacePreviewContent from './WorkspacePreviewContent.jsx';

export default function PreviewPanel({ preview, browser }) {
    return (
        <>
            <SplitHandle onDrag={preview.setSplitPosition} />
            <div className={styles.previewColumn}>
                <TabbedPane
                    tabs={preview.tabs}
                    activeTab={preview.activeTab}
                    onTabChange={preview.setActiveTab}
                    onCloseTab={preview.closeTab}
                >
                    <WorkspacePreviewContent
                        activeTab={preview.activeTab}
                        preview={preview}
                        browser={browser}
                    />
                </TabbedPane>
            </div>
        </>
    );
}
