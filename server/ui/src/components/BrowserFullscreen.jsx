import FullscreenPreview from './FullscreenPreview.jsx';
import ScreencastSurface from './ScreencastSurface.jsx';
import BrowserChrome from './BrowserChrome.jsx';
import styles from './BrowserFullscreen.module.css';

/**
 * Fullscreen view of the selected browser tab. Shares the screencast session
 * (via `control`) and the chrome bar (via `BrowserChrome`) with the inline
 * preview, so the two control bars are identical — only the expand button
 * becomes an exit-fullscreen button here.
 */
export default function BrowserFullscreen({ snapshot, control, onClose }) {
    if (!snapshot) return null;

    const c = control || {};
    const url = c.navUrl || snapshot.url || '';
    const title = c.navTitle || snapshot.title || '';
    const fallbackSrc = snapshot.screenshot
        ? `data:image/png;base64,${snapshot.screenshot}`
        : null;

    return (
        <FullscreenPreview
            onClose={onClose}
            header={
                <BrowserChrome
                    url={url}
                    title={title}
                    control={control}
                    fullscreen
                    onToggleFullscreen={onClose}
                />
            }
        >
            <ScreencastSurface
                frameUrl={c.frameUrl || null}
                fallbackSrc={fallbackSrc}
                engaged={!!c.engaged}
                active
                sendInput={c.sendInput}
                className={styles.imageContainer}
                imgClassName={styles.image}
            />
        </FullscreenPreview>
    );
}
