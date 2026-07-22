import BrowserPreview from '../../components/BrowserPreview.jsx';
import DesktopPreview from '../../components/DesktopPreview.jsx';
import FilePreview from '../../components/FilePreview.jsx';
import GenerationPreview from '../../components/GenerationPreview.jsx';
import TerminalPanel from '../../components/TerminalOutput.jsx';

export default function WorkspacePreviewContent({ activeTab, preview, browser }) {
    if (activeTab === 'browser' && preview.browserTabsList.length > 0) {
        return (
            <BrowserPreview
                tabs={browser.tabs}
                selectedId={browser.selectedTabId}
                onSelectTab={browser.setSelectedTabId}
                onFullscreen={() => preview.setFullscreenItem({ kind: 'browser' })}
                control={browser.control}
                inputActive={preview.fullscreenItem?.kind !== 'browser'}
            />
        );
    }
    if (activeTab?.startsWith('file:')) {
        const fileKey = activeTab.slice(5);
        const file = preview.openFiles.find((item) => (item.path || item.filename) === fileKey);
        return file ? (
            <FilePreview
                item={file}
                onFullscreen={() => preview.setFullscreenItem({ kind: 'file', file })}
            />
        ) : null;
    }
    if (activeTab === 'terminal' && preview.terminalLines.length > 0) {
        return <TerminalPanel lines={preview.terminalLines} />;
    }
    if (activeTab === 'desktop' && preview.desktopActive) {
        return <DesktopPreview visible />;
    }
    if (activeTab === 'generation' && preview.generationPreview) {
        return <GenerationPreview preview={preview.generationPreview} />;
    }
    return null;
}
