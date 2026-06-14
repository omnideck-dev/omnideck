import { useEffect, useRef, useCallback } from 'react';

// DOM MouseEvent.button -> CDP button name.
const BUTTON = ['left', 'middle', 'right'];

// DOM modifier flags -> CDP modifiers bitmask (Alt=1, Ctrl=2, Meta=4, Shift=8).
const modMask = (e) =>
    (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);

/**
 * Renders the live browser image — the screencast frame when present, otherwise
 * the latest screenshot — and, while `engaged`, turns the surface into an input
 * sink: it captures every pointer/keyboard event, suppresses local handling, and
 * forwards low-level primitives via `sendInput` so Chromium reconstructs clicks,
 * drags, and selection itself.
 */
export default function ScreencastSurface({
    frameUrl, fallbackSrc, engaged, active = true, sendInput, className, imgClassName,
}) {
    const surfaceRef = useRef(null);
    const imgRef = useRef(null);
    const moveRaf = useRef(0);

    // Map a DOM event's client coords to page CSS pixels via the image's natural
    // size, so clicks land regardless of how the image is scaled for display.
    const coords = useCallback((e) => {
        const img = imgRef.current;
        const r = img.getBoundingClientRect();
        return {
            x: Math.round((e.clientX - r.left) * (img.naturalWidth / r.width)),
            y: Math.round((e.clientY - r.top) * (img.naturalHeight / r.height)),
        };
    }, []);

    useEffect(() => {
        // Only one surface is the live input target at a time: the inline preview
        // goes inactive while the fullscreen view is open, and vice versa. Because
        // `active` flips on that transition, this effect re-runs and re-focuses the
        // right surface — otherwise focus is left on the unmounted one and keyboard
        // input silently dies after a fullscreen round-trip.
        if (!engaged || !active) return undefined;
        const el = surfaceRef.current;
        if (!el) return undefined;
        el.focus();

        const stop = (e) => { e.preventDefault(); e.stopPropagation(); };

        const onPointerDown = (e) => {
            stop(e); // preventDefault also stops the local browser navigating on the side buttons
            el.focus(); // a click always restores keyboard focus (preventDefault would suppress it)
            // Mouse back/forward side buttons → remote history, not a forwarded click.
            if (e.button === 3) { sendInput({ type: 'back' }); return; }
            if (e.button === 4) { sendInput({ type: 'forward' }); return; }
            el.setPointerCapture?.(e.pointerId);
            const { x, y } = coords(e);
            sendInput({ type: 'mousedown', x, y, button: BUTTON[e.button] || 'left',
                buttons: e.buttons, clickCount: e.detail || 1, mods: modMask(e) });
        };
        const onPointerUp = (e) => {
            stop(e);
            if (e.button === 3 || e.button === 4) return; // history handled on pointerdown
            const { x, y } = coords(e);
            sendInput({ type: 'mouseup', x, y, button: BUTTON[e.button] || 'left',
                buttons: e.buttons, clickCount: e.detail || 1, mods: modMask(e) });
        };
        const onPointerMove = (e) => {
            stop(e);
            if (moveRaf.current) return; // coalesce to one move per frame
            moveRaf.current = requestAnimationFrame(() => {
                moveRaf.current = 0;
                const { x, y } = coords(e);
                sendInput({ type: 'mousemove', x, y, buttons: e.buttons, mods: modMask(e) });
            });
        };
        const onWheel = (e) => {
            stop(e);
            const { x, y } = coords(e);
            sendInput({ type: 'wheel', x, y, dx: e.deltaX, dy: e.deltaY, mods: modMask(e) });
        };
        const onContextMenu = (e) => stop(e); // right-click forwarded as mousedown button=2
        // Bridge host clipboard text into the remote tab.
        const onPaste = (e) => {
            stop(e);
            const t = (e.clipboardData && e.clipboardData.getData('text/plain')) || '';
            if (t) sendInput({ type: 'paste', text: t });
        };
        const onKeyDown = (e) => {
            stop(e);
            // Clipboard chords are bridged to/from the host, not forwarded as keys.
            const mod = e.ctrlKey || e.metaKey;
            const k = e.key.toLowerCase();
            if (mod && k === 'v') return;                         // host paste arrives via the paste event
            if (mod && k === 'c') { sendInput({ type: 'copy' }); return; }
            if (mod && k === 'x') { sendInput({ type: 'copy' }); } // copy to host, then forward the cut
            // Browser history (chrome action, not a page key): Alt+Arrow on
            // Windows/Linux, Cmd+[ / Cmd+] on macOS.
            if ((e.altKey && k === 'arrowleft') || (e.metaKey && k === '[')) { sendInput({ type: 'back' }); return; }
            if ((e.altKey && k === 'arrowright') || (e.metaKey && k === ']')) { sendInput({ type: 'forward' }); return; }
            sendInput({ type: 'keydown', key: e.key, code: e.code, mods: modMask(e) });
            // Printable chars: commit the text separately (keydown alone doesn't type).
            if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
                sendInput({ type: 'text', text: e.key });
            }
        };
        const onKeyUp = (e) => {
            stop(e);
            sendInput({ type: 'keyup', key: e.key, code: e.code, mods: modMask(e) });
        };

        const cap = { capture: true };
        const wheelOpts = { capture: true, passive: false };
        el.addEventListener('pointerdown', onPointerDown, cap);
        el.addEventListener('pointerup', onPointerUp, cap);
        el.addEventListener('pointermove', onPointerMove, cap);
        el.addEventListener('wheel', onWheel, wheelOpts);
        el.addEventListener('contextmenu', onContextMenu, cap);
        el.addEventListener('paste', onPaste, cap);
        el.addEventListener('keydown', onKeyDown, cap);
        el.addEventListener('keyup', onKeyUp, cap);
        return () => {
            el.removeEventListener('pointerdown', onPointerDown, cap);
            el.removeEventListener('pointerup', onPointerUp, cap);
            el.removeEventListener('pointermove', onPointerMove, cap);
            el.removeEventListener('wheel', onWheel, wheelOpts);
            el.removeEventListener('contextmenu', onContextMenu, cap);
            el.removeEventListener('paste', onPaste, cap);
            el.removeEventListener('keydown', onKeyDown, cap);
            el.removeEventListener('keyup', onKeyUp, cap);
            if (moveRaf.current) cancelAnimationFrame(moveRaf.current);
        };
    }, [engaged, active, sendInput, coords]);

    const src = frameUrl || fallbackSrc;
    if (!src) return null;

    return (
        <div ref={surfaceRef} tabIndex={engaged ? 0 : -1} className={className}>
            <img ref={imgRef} src={src} alt="Browser" className={imgClassName} draggable={false} />
        </div>
    );
}
