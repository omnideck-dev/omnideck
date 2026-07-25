import { useEffect, useRef, useState, useCallback } from 'react';

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
 * Owns the workspace's browser control side channel for a conversation.
 *
 * Opens one WebSocket to `/api/browser/control`, streams the CDP screencast of
 * the user-selected tab (re-pointing it whenever the selection changes), and —
 * when control is engaged — forwards input primitives back. Control can only be
 * engaged while no turn is active (`canControl`); a starting turn forces it off.
 *
 * Returns the latest frame for the selected tab, the engage state + toggle, and
 * a `sendInput` for the surface to forward events.
 */
export default function useBrowserControl({ conversationId, selectedTabId, canControl, enabled }) {
    // One latest blob frame per tab, so a tab keeps showing its last frame in
    // the rail after deselection (only the selected tab is streamed live).
    const [framesByTab, setFramesByTab] = useState({});
    const [nav, setNav] = useState(null); // { tabId, url, title } — live nav state
    const [liveTabs, setLiveTabs] = useState(null); // live open-tab list; null = none received yet, [] = authoritatively zero
    const [engaged, setEngaged] = useState(false);
    const [connected, setConnected] = useState(false);
    const [error, setError] = useState(null);
    const wsRef = useRef(null);
    const framesRef = useRef({}); // mirror of framesByTab, for blob-url revocation

    // One socket per conversation, only while a browser view is open.
    useEffect(() => {
        if (!enabled || !conversationId || typeof WebSocket === 'undefined') return undefined;
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(
            `${proto}://${location.host}/api/browser/control?conversation_id=${encodeURIComponent(conversationId)}`,
        );
        setError(null);
        wsRef.current = ws;
        ws.binaryType = 'arraybuffer';
        ws.onopen = () => setConnected(true);
        ws.onmessage = (e) => {
            if (typeof e.data !== 'string') {
                // Binary screencast frame: [int32 tab_id][jpeg bytes]. Cache it
                // per tab, revoking that tab's previous frame.
                const buf = e.data;
                if (!buf || buf.byteLength < 4) return;
                const tabId = new DataView(buf).getInt32(0, false);
                const url = URL.createObjectURL(new Blob([buf.slice(4)], { type: 'image/jpeg' }));
                const prev = framesRef.current[tabId];
                if (prev) URL.revokeObjectURL(prev);
                framesRef.current = { ...framesRef.current, [tabId]: url };
                setFramesByTab(framesRef.current);
                return;
            }
            let m;
            try { m = JSON.parse(e.data); } catch { return; }
            if (m.type === 'nav') {
                setNav({ tabId: m.tab_id, url: m.url, title: m.title });
            } else if (m.type === 'tabs') {
                setLiveTabs(Array.isArray(m.tabs) ? m.tabs : []);
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
            }
        };
        ws.onclose = () => { if (wsRef.current === ws) { wsRef.current = null; setConnected(false); } };
        return () => {
            try { ws.close(); } catch { /* already closing */ }
            wsRef.current = null;
            setConnected(false);
            Object.values(framesRef.current).forEach((u) => URL.revokeObjectURL(u));
            framesRef.current = {};
            setFramesByTab({});
            setLiveTabs(null);
        };
    }, [enabled, conversationId]);

    // Point the screencast at the selected tab. Runs both when the selection
    // changes and once the socket connects, so neither ordering misses the send.
    useEffect(() => {
        const ws = wsRef.current;
        if (connected && ws && ws.readyState === WebSocket.OPEN && selectedTabId != null) {
            ws.send(JSON.stringify({ type: 'select', tab_id: selectedTabId }));
            // Keep the previous tab's cached frame (it's that tab's thumbnail);
            // just drop its nav state until the newly selected tab's arrives.
            setNav(null);
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
            else { URL.revokeObjectURL(cur[id]); changed = true; }
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
                on: engaged && controlAvailable,
            }));
        }
    }, [engaged, controlAvailable, connected]);

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

    const toggleEngage = useCallback(() => {
        setEngaged((v) => (controlAvailable ? !v : false));
    }, [controlAvailable]);

    // The selected tab's cached frame drives the main view; the full per-tab
    // cache drives the rail thumbnails (so deselected tabs keep their frame).
    const frameUrl = selectedTabId != null ? (framesByTab[selectedTabId] || null) : null;
    const navState = nav && nav.tabId === selectedTabId ? nav : null;

    return {
        frameUrl,
        framesByTab,
        navUrl: navState?.url ?? null,
        navTitle: navState?.title ?? null,
        liveTabs,
        connected,
        error,
        engaged: engaged && controlAvailable,
        canControl: controlAvailable,
        toggleEngage,
        sendInput,
        closeTab,
        newTab,
        goto,
        navigate,
    };
}
