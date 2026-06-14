import { useState } from 'react';
import LockIcon from './icons/LockIcon.jsx';
import IconButton from './primitives/IconButton.jsx';
import BrowserNavButtons from './BrowserNavButtons.jsx';
import styles from './BrowserChrome.module.css';

/**
 * Shared browser control bar: the page title above a control row of
 * back/forward/reload, lock, an (editable while engaged) address field,
 * take-control, and an expand / exit-fullscreen button. Rendered identically by
 * the inline preview and the fullscreen view so the two stay consistent;
 * `fullscreen` only flips the right-hand button and adds outer padding.
 */
export default function BrowserChrome({ url, title, control, fullscreen, onToggleFullscreen }) {
    const c = control || {};
    // Local edit buffer for the address field: null = show the live url; a string
    // = the user is editing. Avoids live nav updates clobbering what they type.
    const [edit, setEdit] = useState(null);

    const commitGoto = () => {
        const value = (edit ?? '').trim();
        setEdit(null);
        if (value && c.sendInput) c.sendInput({ type: 'goto', url: value });
    };

    return (
        <div className={`${styles.chrome} ${fullscreen ? styles.fullscreen : ''}`}>
            {title && (
                <div className={styles.pageTitle} title={title}>{title}</div>
            )}
            <div className={styles.urlBar}>
                <BrowserNavButtons control={control} />
                <LockIcon size={12} className={styles.lockIcon} />
                {c.engaged ? (
                    <input
                        className={styles.urlInput}
                        value={edit ?? url ?? ''}
                        onChange={(e) => setEdit(e.target.value)}
                        onFocus={() => setEdit(url ?? '')}
                        onBlur={() => setEdit(null)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') { e.preventDefault(); commitGoto(); e.target.blur(); }
                            if (e.key === 'Escape') { e.preventDefault(); setEdit(null); e.target.blur(); }
                        }}
                        spellCheck={false}
                        aria-label="Address"
                        placeholder="Enter a URL"
                    />
                ) : (
                    <span className={styles.url} title={url}>{url}</span>
                )}
                {c.engaged && c.sendInput && (
                    <IconButton
                        size="sm"
                        onClick={() => c.sendInput({ type: 'new_tab' })}
                        title="New tab"
                        aria-label="New tab"
                        data-testid="browser-new-tab"
                    >
                        <i className="bi bi-plus-lg" style={{ fontSize: 14 }} />
                    </IconButton>
                )}
                {c.toggleEngage && (
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
                {onToggleFullscreen && (
                    <IconButton
                        size="sm"
                        onClick={onToggleFullscreen}
                        title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
                        aria-label={fullscreen ? 'Exit fullscreen' : 'Open fullscreen'}
                        data-testid={fullscreen ? 'browser-fullscreen-exit' : 'browser-fullscreen'}
                    >
                        <i className={`bi ${fullscreen ? 'bi-arrows-angle-contract' : 'bi-arrows-angle-expand'}`} style={{ fontSize: 14 }} />
                    </IconButton>
                )}
            </div>
        </div>
    );
}
