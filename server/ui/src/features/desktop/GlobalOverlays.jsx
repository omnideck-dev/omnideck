import BrowserFullscreen from '../../components/BrowserFullscreen.jsx';
import DesktopPreview from '../../components/DesktopPreview.jsx';
import FilePreview from '../../components/FilePreview.jsx';

export default function GlobalOverlays({
    userDesktopOpen,
    closeUserDesktop,
    preview,
    browser,
}) {
    const selectedBrowserTab = browser.tabs.find((tab) => tab.id === browser.selectedTabId)
        || browser.tabs[0];
    return (
        <>
            {userDesktopOpen && (
                <DesktopPreview visible onClose={closeUserDesktop} overlay />
            )}
            {preview.fullscreenItem?.kind === 'file' && (
                <FilePreview
                    item={preview.fullscreenItem.file}
                    fullscreen
                    onClose={() => preview.setFullscreenItem(null)}
                />
            )}
            {preview.fullscreenItem?.kind === 'browser' && selectedBrowserTab && (
                <BrowserFullscreen
                    snapshot={selectedBrowserTab.snapshot}
                    control={browser.control}
                    onClose={() => preview.setFullscreenItem(null)}
                />
            )}
        </>
    );
}
