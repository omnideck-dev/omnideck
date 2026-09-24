import { useEffect, useRef } from 'react';

import styles from './CustomAppHost.module.css';

/** Trusted same-origin frame plus convenience bridges owned by Omnideck. */
export default function CustomAppHost({
    app,
    reloadSignal = 0,
    visible = true,
    onOpenChat,
    onComposeChat,
}) {
    const frameRef = useRef(null);
    const appUrl = `/api/custom-apps/${encodeURIComponent(app.slug)}/web/`;

    // Keep the host frame on the app entry document. Apps may render files or
    // nested frames inside that document; only replacement of the host is undone.
    const restoreAppEntryAfterNavigation = () => {
        const frame = frameRef.current;
        if (!frame) return;
        try {
            const loadedUrl = new URL(frame.contentWindow.location.href);
            const entryUrl = new URL(appUrl, window.location.href);
            loadedUrl.hash = '';
            entryUrl.hash = '';
            if (loadedUrl.href === entryUrl.href) return;
        } catch {
            // Cross-origin frame locations are intentionally unreadable.
        }
        frame.src = appUrl;
    };

    useEffect(() => {
        const receiveMessage = async (event) => {
            if (event.source !== frameRef.current?.contentWindow) return;
            // The WindowProxy survives iframe navigation, so also reject messages
            // after the app navigates its frame to an external origin.
            if (event.origin !== window.location.origin) return;
            const message = event.data;
            if (!message || typeof message !== 'object') return;

            if (message.type === 'omnideck:chat-open') {
                onOpenChat?.();
                return;
            }
            if (message.type === 'omnideck:chat-compose') {
                if (typeof message.text !== 'string' || message.text.length > 20000) return;
                onComposeChat?.({ text: message.text, context: message.context });
                return;
            }
            if (message.type !== 'omnideck:invoke' || typeof message.id !== 'string') return;
            if (!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(message.action)) return;

            let responseMessage;
            try {
                const response = await fetch(
                    `/api/custom-apps/${encodeURIComponent(app.slug)}/invoke/${encodeURIComponent(message.action)}`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ args: message.args || {} }),
                    },
                );
                const body = await response.json();
                responseMessage = {
                    type: 'omnideck:result',
                    id: message.id,
                    ok: response.ok && body.ok,
                    result: body.result,
                    error: body.error,
                };
            } catch (err) {
                responseMessage = {
                    type: 'omnideck:result',
                    id: message.id,
                    ok: false,
                    error: { code: 'BRIDGE_ERROR', message: err.message || 'Could not invoke app action' },
                };
            }
            frameRef.current?.contentWindow?.postMessage(responseMessage, window.location.origin);
        };

        window.addEventListener('message', receiveMessage);
        return () => window.removeEventListener('message', receiveMessage);
    }, [app, onOpenChat, onComposeChat]);

    return (
        <div className={`${styles.frameWell} ${!visible ? styles.hidden : ''}`}>
            {/* This same-origin URL serves the app's web/index.html and its relative assets. */}
            <iframe
                key={`${app.slug}-${reloadSignal}`}
                ref={frameRef}
                className={styles.frame}
                src={appUrl}
                onLoad={restoreAppEntryAfterNavigation}
                title={app.title}
                data-testid="custom-app-frame"
            />
        </div>
    );
}
