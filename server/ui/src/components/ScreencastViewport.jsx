import { useEffect, useRef, useCallback, useState } from 'react';

// DOM MouseEvent.button -> CDP button name.
const BUTTON = ['left', 'middle', 'right'];

// DOM modifier flags -> CDP modifiers bitmask (Alt=1, Ctrl=2, Meta=4, Shift=8).
const modMask = (e) =>
    (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);

/**
 * Renders the live browser image and, while `engaged`, turns the viewport into
 * an input sink: it captures every pointer/keyboard event, suppresses local
 * handling, and forwards low-level primitives via `sendInput` so Chromium
 * reconstructs clicks, drags, and selection itself.
 *
 * Frames arrive on `frameBus` rather than through props, and are painted to a
 * canvas inside an animation frame. Keeping them out of React is what stops a
 * live view from re-rendering the app tens of times a second, and drawing on the
 * frame boundary is what stops a paint landing halfway through one.
 */
export default function ScreencastViewport({
    frameBus, fallbackSrc, engaged, active = true, sendInput, cursor = 'default',
    className, imgClassName, viewportRef: externalRef,
}) {
    // The parent may own the viewport ref (to refocus it, e.g. after an
    // address-bar navigation); fall back to a local one when it doesn't.
    const internalRef = useRef(null);
    const viewportRef = externalRef || internalRef;
    const canvasRef = useRef(null);
    const flushRaf = useRef(0);
    const pendingMove = useRef(null); // newest pointer sample, not the first
    const pendingWheel = useRef(null); // accumulated wheel delta for this frame
    // Whether anything has been drawn yet. One state flip, not one per frame: it
    // only decides whether the canvas is worth showing.
    const [painted, setPainted] = useState(false);
    // Set once a live frame lands, so a slow-loading fallback screenshot can
    // never paint over the live view.
    const live = useRef(false);
    // Frame geometry, kept in a ref so the coordinate mapping never depends on a
    // render. Written by the paint loop, read by the pointer handlers.
    const geometry = useRef({
        width: 0, height: 0, deviceWidth: 0, deviceHeight: 0, pageScale: 1, offsetTop: 0,
    });

    // ---- painting ----------------------------------------------------------
    useEffect(() => {
        if (!frameBus) return undefined;
        let raf = 0;
        let queued = null;

        const paint = () => {
            raf = 0;
            const frame = queued;
            queued = null;
            const canvas = canvasRef.current;
            if (!frame || !canvas) return;
            const { bitmap, meta } = frame;
            if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
                canvas.width = bitmap.width;
                canvas.height = bitmap.height;
            }
            geometry.current = {
                width: bitmap.width,
                height: bitmap.height,
                deviceWidth: meta.deviceWidth || bitmap.width,
                deviceHeight: meta.deviceHeight || bitmap.height,
                pageScale: meta.pageScale || 1,
                offsetTop: meta.offsetTop || 0,
            };
            const ctx = canvas.getContext('2d', { alpha: false });
            if (ctx) ctx.drawImage(bitmap, 0, 0);
            live.current = true;
            setPainted(true);
        };

        const onFrame = (frame) => {
            // A superseded frame is simply overwritten: only the newest one is
            // worth painting, and the bus closes the bitmaps it replaces.
            queued = frame;
            if (!raf) raf = requestAnimationFrame(paint);
        };

        if (frameBus.current) onFrame(frameBus.current);
        const unsubscribe = frameBus.subscribe(onFrame);
        return () => {
            unsubscribe();
            if (raf) cancelAnimationFrame(raf);
        };
    }, [frameBus]);

    // Until the channel delivers a frame, draw the agent's last screenshot into
    // the same canvas. One element always holds the browser image, so nothing
    // swaps underneath the input listeners or the callers watching for it.
    useEffect(() => {
        if (!fallbackSrc || live.current) return undefined;
        let cancelled = false;
        const img = new Image();
        img.onload = () => {
            const canvas = canvasRef.current;
            if (cancelled || live.current || !canvas) return;
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            // A screenshot carries no metadata, so treat its pixels as page
            // pixels. That is only a guess, but the view is not interactive
            // until a real frame with real geometry arrives.
            geometry.current = {
                width: img.naturalWidth,
                height: img.naturalHeight,
                deviceWidth: img.naturalWidth,
                deviceHeight: img.naturalHeight,
                pageScale: 1,
                offsetTop: 0,
            };
            canvas.getContext('2d', { alpha: false })?.drawImage(img, 0, 0);
            setPainted(true);
        };
        img.src = fallbackSrc;
        return () => { cancelled = true; };
    }, [fallbackSrc]);

    // Map a DOM event's client coords to page CSS pixels. The canvas holds a
    // scaled capture, so its pixel size is not the page's coordinate space; the
    // frame metadata carries the CSS viewport size it corresponds to.
    const coords = useCallback((e) => {
        const canvas = canvasRef.current;
        const g = geometry.current;
        if (!canvas || !g.width || !g.height) return { x: 0, y: 0 };
        const r = canvas.getBoundingClientRect();
        if (!r.width || !r.height) return { x: 0, y: 0 };
        const imgX = (e.clientX - r.left) * (g.width / r.width);
        const imgY = (e.clientY - r.top) * (g.height / r.height);
        return {
            x: Math.round((imgX * (g.deviceWidth / g.width)) / g.pageScale),
            // offsetTop is a non-content band at the top of a capture. It is zero
            // except under device emulation that draws top controls.
            y: Math.round((imgY * (g.deviceHeight / g.height)) / g.pageScale - g.offsetTop),
        };
    }, []);

    // ---- input -------------------------------------------------------------
    useEffect(() => {
        // Only the selected Browser tab is the live input target. Desktop Layout
        // moves and fullscreen transitions preserve this mounted element, so its
        // screencast session and keyboard focus do not need to be recreated.
        if (!engaged || !active) return undefined;
        const el = viewportRef.current;
        if (!el) return undefined;
        el.focus();

        const stop = (e) => { e.preventDefault(); e.stopPropagation(); };

        // Pointer and wheel events need the page's coordinate space, which only
        // arrives with a live frame's metadata. Until then the canvas may still
        // be showing the agent's screenshot, whose pixels are not page pixels, so
        // forwarding would put the click somewhere the user did not aim. Dropping
        // it is better than landing it in the wrong place. Keystrokes carry no
        // coordinates and are unaffected.
        const positioned = () => live.current;

        // One coalesced flush per animation frame for moves and wheel, so a
        // trackpad emitting 120 events a second cannot outrun the channel.
        const flush = () => {
            if (flushRaf.current) {
                cancelAnimationFrame(flushRaf.current);
                flushRaf.current = 0;
            }
            const move = pendingMove.current;
            pendingMove.current = null;
            if (move) sendInput(move);
            const wheel = pendingWheel.current;
            pendingWheel.current = null;
            if (wheel) sendInput(wheel);
        };
        const schedule = () => {
            if (!flushRaf.current) flushRaf.current = requestAnimationFrame(flush);
        };

        const onPointerDown = (e) => {
            stop(e); // preventDefault also stops the local browser navigating on the side buttons
            el.focus(); // a click always restores keyboard focus (preventDefault would suppress it)
            // Mouse back/forward side buttons → remote history, not a forwarded click.
            if (e.button === 3) { sendInput({ type: 'back' }); return; }
            if (e.button === 4) { sendInput({ type: 'forward' }); return; }
            el.setPointerCapture?.(e.pointerId);
            if (!positioned()) return;
            flush(); // a press must not land ahead of the move that positioned it
            const { x, y } = coords(e);
            sendInput({ type: 'mousedown', x, y, button: BUTTON[e.button] || 'left',
                buttons: e.buttons, clickCount: e.detail || 1, mods: modMask(e) });
        };
        const onPointerUp = (e) => {
            stop(e);
            if (e.button === 3 || e.button === 4) return; // history handled on pointerdown
            if (!positioned()) return;
            flush();
            const { x, y } = coords(e);
            sendInput({ type: 'mouseup', x, y, button: BUTTON[e.button] || 'left',
                buttons: e.buttons, clickCount: e.detail || 1, mods: modMask(e) });
        };
        const onPointerMove = (e) => {
            stop(e);
            if (!positioned()) return;
            // Keep the newest sample. Holding the first one of each frame sends a
            // position that is already stale by the time it goes out.
            const { x, y } = coords(e);
            pendingMove.current = { type: 'mousemove', x, y, buttons: e.buttons, mods: modMask(e) };
            schedule();
        };
        const onWheel = (e) => {
            stop(e);
            if (!positioned()) return;
            const { x, y } = coords(e);
            const prev = pendingWheel.current;
            // Sum the deltas so collapsing a burst scrolls the same distance.
            pendingWheel.current = {
                type: 'wheel', x, y,
                dx: (prev?.dx || 0) + e.deltaX,
                dy: (prev?.dy || 0) + e.deltaY,
                mods: modMask(e),
            };
            schedule();
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
            // One message per keystroke. The keydown carries its own text now, so
            // the character needs no second round trip that could also arrive out
            // of order with the keystroke that produced it.
            sendInput({ type: 'keydown', key: e.key, code: e.code, mods: modMask(e), repeat: e.repeat });
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
            if (flushRaf.current) cancelAnimationFrame(flushRaf.current);
            flushRaf.current = 0;
            pendingMove.current = null;
            pendingWheel.current = null;
        };
    }, [engaged, active, sendInput, coords]);

    // The canvas is always mounted: unmounting the viewport on a transient empty
    // frame (mid tab-switch) drops the input listeners and keyboard focus bound
    // to it. It is only hidden before anything has been drawn into it.
    return (
        <div
            ref={viewportRef}
            tabIndex={engaged ? 0 : -1}
            className={className}
            data-testid="browser-viewport"
            style={engaged ? { cursor } : undefined}
        >
            <canvas
                ref={canvasRef}
                className={imgClassName}
                aria-label="Browser"
                data-testid="browser-frame"
                hidden={!painted}
            />
        </div>
    );
}
