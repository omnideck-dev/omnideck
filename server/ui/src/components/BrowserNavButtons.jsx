import IconButton from './primitives/IconButton.jsx';

/**
 * Back / forward / reload controls for the takeover browser. Only rendered
 * while control is engaged (the hook's `engaged` already implies an idle turn),
 * since history navigation is part of driving the browser, not passive viewing.
 */
export default function BrowserNavButtons({ control }) {
    const c = control || {};
    if (!c.engaged || !c.sendInput) return null;
    const nav = (dir) => c.sendInput({ type: dir });
    return (
        <>
            <IconButton size="sm" onClick={() => nav('back')} title="Back" aria-label="Back">
                <i className="bi bi-arrow-left" style={{ fontSize: 14 }} />
            </IconButton>
            <IconButton size="sm" onClick={() => nav('forward')} title="Forward" aria-label="Forward">
                <i className="bi bi-arrow-right" style={{ fontSize: 14 }} />
            </IconButton>
            <IconButton size="sm" onClick={() => nav('reload')} title="Reload" aria-label="Reload">
                <i className="bi bi-arrow-clockwise" style={{ fontSize: 14 }} />
            </IconButton>
        </>
    );
}
