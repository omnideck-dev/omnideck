import { useState } from 'react';
import LockIcon from './icons/LockIcon.jsx';
import IconButton from './primitives/IconButton.jsx';
import BrowserNavButtons from './BrowserNavButtons.jsx';
import styles from './BrowserChrome.module.css';

/**
 * Shared browser control bar: the page title above a control row of
 * back/forward/reload, lock, an (editable while engaged) address field,
 * and take-control. Full-screen presentation belongs to Desktop Layout rather
 * than to this feature component.
 */
export default function BrowserChrome({ url, title, control, focusViewport }) {
    const c = control || {};
    // Local edit buffer for the address field: null = show the live url; a string
    // = the user is editing. Avoids live nav updates clobbering what they type.
    const [edit, setEdit] = useState(null);

    const commitGoto = () => {
        const value = (edit ?? '').trim();
        setEdit(null);
        if (value && c.goto) c.goto(value);
    };

    return (
        <div className={styles.chrome}>
            {/* Always render the title row (with a fallback) so its height is
                constant — an empty row would shift the preview as pages with and
                without a title alternate. */}
            <div className={styles.pageTitle} data-testid="browser-page-title" title={title || 'Untitled'}>{title || 'Untitled'}</div>
            <div className={styles.urlBar}>
                <BrowserNavButtons control={control} />
                <LockIcon size={12} className={styles.lockIcon} />
                {c.engaged ? (
                    <input
                        className={styles.urlInput}
                        data-testid="browser-address"
                        value={edit ?? url ?? ''}
                        onChange={(e) => setEdit(e.target.value)}
                        onFocus={() => setEdit(url ?? '')}
                        onBlur={() => setEdit(null)}
                        onKeyDown={(e) => {
                            // Hand focus back to the viewport so the page is
                            // immediately typeable. Blur is the fallback when no
                            // viewport is wired—otherwise focus sits on the
                            // document body and its key listener receives
                            // nothing.
                            const target = e.target;
                            const restoreFocus = () => (
                                focusViewport ? focusViewport() : target.blur()
                            );
                            if (e.key === 'Enter') { e.preventDefault(); commitGoto(); restoreFocus(); }
                            if (e.key === 'Escape') { e.preventDefault(); setEdit(null); restoreFocus(); }
                        }}
                        spellCheck={false}
                        aria-label="Address"
                        placeholder="Enter a URL"
                    />
                ) : (
                    <span className={styles.url} title={url}>{url}</span>
                )}
                {control && c.error && (
                    <span
                        className={styles.controlError}
                        role="status"
                        title={`Browser control unavailable: ${c.error}`}
                        data-testid="browser-control-error"
                    >
                        {c.error}
                    </span>
                )}
                {c.engaged && c.newTab && (
                    <IconButton
                        size="sm"
                        onClick={c.newTab}
                        title="New tab"
                        aria-label="New tab"
                        data-testid="browser-new-tab"
                    >
                        <i className="bi bi-plus-lg" style={{ fontSize: 14 }} />
                    </IconButton>
                )}
                {control && c.toggleEngage && (
                    <IconButton
                        size="sm"
                        onClick={c.toggleEngage}
                        disabled={!c.canControl}
                        title={c.engaged ? 'Release control' : (c.canControl ? 'Take control' : 'Stop the agent to take control')}
                        aria-label="Take control of browser"
                        data-testid="browser-take-control"
                    >
                        <i className={`bi ${c.engaged ? 'bi-pause-circle' : 'bi-mouse'}`} style={{ fontSize: 14 }} />
                    </IconButton>
                )}
            </div>
        </div>
    );
}
