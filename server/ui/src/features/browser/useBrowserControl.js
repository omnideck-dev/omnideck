import { useEffect, useRef, useState, useCallback } from 'react';
import createFrameBus from './frameBus.js';

// Binary frame header: int32 tab id, then float32 deviceWidth, deviceHeight,
// pageScaleFactor, offsetTop. Those four are what turn a point on the displayed
// image back into a page coordinate; the image's own pixel size cannot, because
// capture is scaled down to the size actually on screen.
const FRAME_HEADER_BYTES = 20;

// Thumbnails only need to look current, so they refresh on a slow timer instead
// of once per frame. This is the only place a frame reaches React state.
const THUMB_INTERVAL_MS = 1000;
const RECONNECT_DELAY_MS = 250;
const MAX_RECONNECT_ATTEMPTS = 20;

/**
 * @typedef {{ type: 'user' }
 *   | { type: 'conversation', conversationId: string }
 * } BrowserControlTarget
 */

/**
 * Write text to the host clipboard. Uses the async Clipboard API on secure
 * origins (https / localhost); falls back to a hidden-textarea execCommand on
 * plain-http hosts where `navigator.clipboard` is unavailable. Both paths rely
 * on the recent Ctrl/Cmd+C gesture's transient activation.
 */
function writeHostClipboard(text) {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).catch(() => _execCopyFallback(text));
        return;
    }
    _execCopyFallback(text);
}

function _execCopyFallback(text) {
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
    } catch { /* clipboard unavailable in this context */ }
}

/**
 * Prompt the host user to pick file(s) for a remote file dialog and resolve to
 * `[{ name, mime, data(base64) }]` (empty if cancelled). Runs within the
 * forwarded-click's user-gesture window so the picker is allowed to open.
 */
function requestHostFiles(multiple) {
    return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = !!multiple;
        input.style.display = 'none';
        let settled = false;
        const finish = (payloads) => {
            if (settled) return;
            settled = true;
            input.remove();
            resolve(payloads);
        };
        input.onchange = async () => {
            const files = Array.from(input.files || []);
            finish(await Promise.all(files.map(_readFilePayload)));
        };
        // File inputs have no cancel event; treat a refocus with no change as cancel.
        window.addEventListener('focus', () => setTimeout(() => finish([]), 400), { once: true });
        document.body.appendChild(input);
        input.click();
    });
}

async function _readFilePayload(file) {
    const buf = new Uint8Array(await file.arrayBuffer());
    let bin = '';
    const chunk = 0x8000;
    for (let i = 0; i < buf.length; i += chunk) {
        bin += String.fromCharCode.apply(null, buf.subarray(i, i + chunk));
    }
    return { name: file.name, mime: file.type, data: btoa(bin) };
}

/**
 * Owns one mounted Browser view's live control side channel.
 *
 * Opens one WebSocket to `/api/browser/control`, scoped either to the user's
 * Browser or a conversation's root-agent Browser. It streams the selected tab's
 * CDP screencast and forwards input while control is engaged. Conversation
 * callers decide when takeover is allowed through `canControl`; the user Browser
 * passes `alwaysEngaged` because it is never agent-controlled.
 *
 * Returns the latest frame for the selected tab, the engage state + toggle, and
 * a `sendInput` for the surface to forward events.
 */
/**
 * @param {object} options
 * @param {BrowserControlTarget | null} options.target
 * @param {number | null} options.selectedTabId
 * @param {boolean} options.canControl
 * @param {boolean} options.enabled
 * @param {boolean} [options.alwaysEngaged]
 * @param {string | number | null} [options.sessionKey]
 */
export default function useBrowserControl({
    target,
    selectedTabId,
    canControl,
    enabled,
    alwaysEngaged = false,
    sessionKey = null,
}) {
    const targetType = target?.type ?? null;
    const conversationId = target?.type === 'conversation'
        ? target.conversationId
        : null;
    // One latest blob frame per tab, so a tab keeps showing its last frame in
    // the rail after deselection (only the selected tab is streamed live).
    const [framesByTab, setFramesByTab] = useState({});
    const [nav, setNav] = useState(null); // { tabId, url, title } — live nav state
    const [liveTabs, setLiveTabs] = useState(null); // live open-tab list; null = none received yet, [] = authoritatively zero
    const [engaged, setEngaged] = useState(false);
    const [connected, setConnected] = useState(false);
    const [error, setError] = useState(null);
    const [connectionAttempt, setConnectionAttempt] = useState(0);
    // The cursor the remote page would show. The screencast image carries no
    // cursor, so without mirroring it the pointer stays an arrow over links.
    const [cursor, setCursor] = useState('default');
    const wsRef = useRef(null);
    const connectedOnceRef = useRef(false);
    const reconnectAttemptsRef = useRef(0);
    const reconnectTimerRef = useRef(null);
    const framesRef = useRef({}); // mirror of framesByTab, for blob-url revocation
    const thumbAtRef = useRef({}); // per-tab timestamp of the last thumbnail refresh
    // Live frames bypass React entirely; the viewport subscribes to this.
    const frameBusRef = useRef(null);
    if (frameBusRef.current === null) frameBusRef.current = createFrameBus();
    const frameBus = frameBusRef.current;

    // One socket per mounted, enabled control surface. User and conversation
    // Browser views may therefore each have an independent live connection.
    useEffect(() => {
        if (
            !enabled
            || !targetType
            || (targetType === 'conversation' && !conversationId)
            || typeof WebSocket === 'undefined'
        ) return undefined;
        let disposed = false;
        const scheduleReconnect = () => {
            if (
                disposed
                || !connectedOnceRef.current
                || reconnectTimerRef.current !== null
                || reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS
            ) return;
            reconnectAttemptsRef.current += 1;
            reconnectTimerRef.current = setTimeout(() => {
                reconnectTimerRef.current = null;
                if (!disposed) setConnectionAttempt((attempt) => attempt + 1);
            }, RECONNECT_DELAY_MS);
        };
        const markHealthy = () => {
            connectedOnceRef.current = true;
            reconnectAttemptsRef.current = 0;
            setError(null);
        };
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const query = targetType === 'user'
            ? 'scope=user'
            : `conversation_id=${encodeURIComponent(conversationId)}`;
        const ws = new WebSocket(
            `${proto}://${location.host}/api/browser/control?${query}`,
        );
        // A server rejection remains sticky for this ownership attempt so we
        // do not create a reconnect loop. Hiding/reselecting the Browser or
        // changing conversations creates a new attempt and clears the error.
        setError(null);
        wsRef.current = ws;
        ws.binaryType = 'arraybuffer';
        ws.onopen = () => setConnected(true);
        ws.onmessage = (e) => {
            if (typeof e.data !== 'string') {
                const buf = e.data;
                if (!buf || buf.byteLength < FRAME_HEADER_BYTES) return;
                const head = new DataView(buf, 0, FRAME_HEADER_BYTES);
                const tabId = head.getInt32(0, false);
                const meta = {
                    deviceWidth: head.getFloat32(4, false),
                    deviceHeight: head.getFloat32(8, false),
                    pageScale: head.getFloat32(12, false) || 1,
                    offsetTop: head.getFloat32(16, false),
                };
                const jpeg = buf.slice(FRAME_HEADER_BYTES);
                markHealthy();
                const seq = frameBus.nextSeq();
                // createImageBitmap decodes off the main thread, so a busy page
                // does not stall the UI thread once per frame the way assigning
                // a blob url to an <img> does.
                createImageBitmap(new Blob([jpeg], { type: 'image/jpeg' }))
                    .then((bitmap) => frameBus.push({ bitmap, meta, tabId, seq }))
                    .catch(() => { /* malformed frame, wait for the next */ });

                // Refresh this tab's rail thumbnail occasionally, not per frame.
                const now = Date.now();
                if (now - (thumbAtRef.current[tabId] || 0) >= THUMB_INTERVAL_MS) {
                    thumbAtRef.current[tabId] = now;
                    const url = URL.createObjectURL(new Blob([jpeg], { type: 'image/jpeg' }));
                    const prev = framesRef.current[tabId];
                    if (prev) URL.revokeObjectURL(prev);
                    framesRef.current = { ...framesRef.current, [tabId]: url };
                    setFramesByTab(framesRef.current);
                }
                return;
            }
            let m;
            try { m = JSON.parse(e.data); } catch { return; }
            if (m.type === 'nav') {
                markHealthy();
                setNav({ tabId: m.tab_id, url: m.url, title: m.title });
            } else if (m.type === 'tabs') {
                markHealthy();
                setLiveTabs(Array.isArray(m.tabs) ? m.tabs : []);
            } else if (m.type === 'cursor') {
                setCursor(m.cursor || 'default');
            } else if (m.type === 'clipboard' && m.text) {
                // Selection copied in the remote tab → write to the host clipboard.
                writeHostClipboard(m.text);
            } else if (m.type === 'filechooser') {
                // Remote page opened a file dialog → pick on the host, send back.
                requestHostFiles(m.multiple).then((files) => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'file', files }));
                    }
                });
            } else if (m.type === 'error') {
                // Keep server rejections visible to the renderer. In
                // particular, no_active_browser used to be swallowed while an
                // enabled takeover button remained on screen.
                setError(m.reason || 'browser_control_error');
                setConnected(false);
                setEngaged(false);
                scheduleReconnect();
            }
        };
        ws.onclose = () => {
            if (wsRef.current === ws) {
                wsRef.current = null;
                setConnected(false);
                scheduleReconnect();
            }
        };
        return () => {
            disposed = true;
            try { ws.close(); } catch { /* already closing */ }
            wsRef.current = null;
            setConnected(false);
            Object.values(framesRef.current).forEach((u) => URL.revokeObjectURL(u));
            framesRef.current = {};
            thumbAtRef.current = {};
            frameBus.reset();
            setFramesByTab({});
            setLiveTabs(null);
            setCursor('default');
        };
    }, [enabled, conversationId, connectionAttempt, frameBus, sessionKey, targetType]);

    useEffect(() => () => {
        if (reconnectTimerRef.current !== null) {
            clearTimeout(reconnectTimerRef.current);
            reconnectTimerRef.current = null;
        }
        connectedOnceRef.current = false;
        reconnectAttemptsRef.current = 0;
    }, [enabled, conversationId, sessionKey, targetType]);

    // Point the screencast at the selected tab. Runs both when the selection
    // changes and once the socket connects, so neither ordering misses the send.
    useEffect(() => {
        const ws = wsRef.current;
        if (connected && ws && ws.readyState === WebSocket.OPEN && selectedTabId != null) {
            ws.send(JSON.stringify({ type: 'select', tab_id: selectedTabId }));
            // Keep the previous tab's cached frame (it's that tab's thumbnail);
            // just drop its nav state until the newly selected tab's arrives.
            setNav(null);
            setCursor('default');
        }
    }, [connected, selectedTabId]);

    // Drop cached frames for tabs that have closed, freeing their blob urls.
    useEffect(() => {
        if (liveTabs == null) return;
        const open = new Set(liveTabs.map((t) => String(t.id)));
        const cur = framesRef.current;
        const next = {};
        let changed = false;
        for (const id of Object.keys(cur)) {
            if (open.has(id)) next[id] = cur[id];
            else {
                URL.revokeObjectURL(cur[id]);
                delete thumbAtRef.current[id];
                changed = true;
            }
        }
        if (changed) { framesRef.current = next; setFramesByTab(next); }
    }, [liveTabs]);

    // A connected channel is part of control eligibility. The caller supplies
    // conversation state (for example, whether an agent is streaming); this
    // hook adds the transport requirement it alone can know.
    const controlAvailable = canControl && connected && !error;

    // A turn starting revokes control.
    useEffect(() => {
        if (!controlAvailable) setEngaged(false);
    }, [controlAvailable]);

    // Tell the backend whether the human holds control (gates remote file dialogs).
    useEffect(() => {
        const ws = wsRef.current;
        if (connected && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'engage',
                on: (alwaysEngaged || engaged) && controlAvailable,
            }));
        }
    }, [alwaysEngaged, engaged, controlAvailable, connected]);

    // Low-level: forward a raw input primitive (mouse/key/wheel/text) over the
    // channel. The screencast surface streams these; discrete commands below
    // wrap it so consumers express intent rather than hand-build wire messages.
    const sendInput = useCallback((obj) => {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    }, []);

    // Discrete commands — the wire-protocol shapes live here, not in components.
    const closeTab = useCallback((tabId) => sendInput({ type: 'close_tab', tab_id: tabId }), [sendInput]);
    const newTab = useCallback(() => sendInput({ type: 'new_tab' }), [sendInput]);
    const goto = useCallback((url) => sendInput({ type: 'goto', url }), [sendInput]);
    const navigate = useCallback((direction) => sendInput({ type: direction }), [sendInput]);
    // Ask for capture at the width it is displayed at. Capturing the whole 1080p
    // window and letting the client shrink it wastes most of every frame, which
    // is what caps the frame rate on a busy page. Width alone sets the scale,
    // because the frame is always shown at the view's full width.
    const resize = useCallback(
        (width) => sendInput({ type: 'resize', width: Math.round(width) }),
        [sendInput],
    );

    const toggleEngage = useCallback(() => {
        setEngaged((v) => (controlAvailable ? !v : false));
    }, [controlAvailable]);

    // The live view reads frames off the bus; the per-tab blob cache only feeds
    // the rail thumbnails (so deselected tabs keep showing something).
    const navState = nav && nav.tabId === selectedTabId ? nav : null;

    return {
        frameBus,
        framesByTab,
        cursor,
        navUrl: navState?.url ?? null,
        navTitle: navState?.title ?? null,
        liveTabs,
        connected,
        error,
        engaged: (alwaysEngaged || engaged) && controlAvailable,
        canControl: controlAvailable,
        toggleEngage: alwaysEngaged ? null : toggleEngage,
        sendInput,
        closeTab,
        newTab,
        goto,
        navigate,
        resize,
    };
}
