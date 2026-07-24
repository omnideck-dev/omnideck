import { useRef, useCallback, useEffect } from 'react';
import styles from './BrowserPreview.module.css';
import ScreencastSurface from './ScreencastSurface.jsx';
import BrowserChrome from './BrowserChrome.jsx';

/** Extract a short host label from a URL for the thumbnail caption. */
function _hostOf(url) {
    if (!url) return '';
    try {
        return new URL(url).host.replace(/^www\./, '');
    } catch {
        return url;
    }
}

/**
 * `tabs` is an array of ``{ id, snapshot }`` for every open browser tab.
 * Selection is controlled by the parent (`selectedId` / `onSelectTab`).
 * `control` carries the live screencast frame + nav state for the selected tab.
 */
export default function BrowserPreview({ tabs, selectedId, onSelectTab, control, inputActive = true }) {
    const activeTab = tabs.find(t => t.id === selectedId) || tabs[0];
    if (!activeTab) return null;

    const activeSnapshot = activeTab.snapshot;
    const fallbackSrc = activeSnapshot.screenshot
        ? `data:image/png;base64,${activeSnapshot.screenshot}`
        : null;
    const showRail = tabs.length > 1;
    const c = control || {};
    // Own the surface ref so the address bar can refocus it after navigating.
    const surfaceRef = useRef(null);
    const focusSurface = useCallback(() => surfaceRef.current?.focus(), []);
    // Switching tabs (or opening one) moves focus to the clicked rail / new-tab
    // button. Return it to the surface so the page stays keyboard-interactive
    // without having to toggle control off and on.
    useEffect(() => {
        if (c.engaged) focusSurface();
    }, [selectedId, c.engaged, focusSurface]);
    // Prefer the live nav state (updates during takeover / agent nav); fall back
    // to the screenshot snapshot.
    const url = c.navUrl || activeSnapshot.url;
    const title = c.navTitle || activeSnapshot.title;

    return (
        <div className={styles.content} data-testid="browser-preview">
            <BrowserChrome
                url={url}
                title={title}
                control={control}
                focusSurface={focusSurface}
            />

            <ScreencastSurface
                frameUrl={c.frameUrl || null}
                fallbackSrc={fallbackSrc}
                engaged={!!c.engaged}
                active={inputActive}
                sendInput={c.sendInput}
                className={styles.screenshotContainer}
                imgClassName={styles.screenshot}
                surfaceRef={surfaceRef}
            />

            {showRail && (
                <div className={styles.thumbRail} role="tablist" aria-label="Open browser tabs" data-testid="browser-tab-rail">
                    {tabs.map(({ id, snapshot: tabSnap }) => {
                        const isActive = id === activeTab.id;
                        // Prefer the tab's live screencast frame (cached per tab,
                        // so it survives deselection); fall back to the agent's
                        // screenshot. Tabs opened during takeover have no agent
                        // screenshot, so the cached frame is all they have.
                        const liveFrame = c.framesByTab ? c.framesByTab[id] : null;
                        const thumbSrc = liveFrame
                            || (tabSnap.screenshot ? `data:image/png;base64,${tabSnap.screenshot}` : null);
                        const host = _hostOf(tabSnap.url);
                        return (
                            <div key={id} className={styles.thumbWrap}>
                                <button
                                    type="button"
                                    role="tab"
                                    aria-selected={isActive}
                                    data-testid={`browser-tab-${id}`}
                                    title={tabSnap.title || tabSnap.url}
                                    className={`${styles.thumbCard} ${isActive ? styles.thumbCardActive : ''}`}
                                    onClick={() => { if (onSelectTab) onSelectTab(id); if (c.engaged) focusSurface(); }}
                                >
                                    <div className={styles.thumbFrame}>
                                        {thumbSrc && (
                                            <img src={thumbSrc} alt="" className={styles.thumbImg} />
                                        )}
                                    </div>
                                    <div className={styles.thumbMeta}>{host || tabSnap.url || 'New tab'}</div>
                                </button>
                                {c.engaged && c.closeTab && (
                                    <button
                                        type="button"
                                        className={styles.thumbClose}
                                        data-testid={`browser-tab-close-${id}`}
                                        title="Close tab"
                                        aria-label="Close tab"
                                        onClick={() => c.closeTab(id)}
                                    >
                                        <i className="bi bi-x" />
                                    </button>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
