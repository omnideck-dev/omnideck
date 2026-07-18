import { useEffect, useRef } from 'react';

import styles from './FolderAppHost.module.css';

/** Sandboxed frame plus the narrow action/chat bridge owned by Omnideck. */
export default function FolderAppHost({
    app,
    reloadSignal = 0,
    active = true,
    onOpenChat,
    onComposeChat,
}) {
    const frameRef = useRef(null);

    useEffect(() => {
        const receiveMessage = async (event) => {
            if (event.source !== frameRef.current?.contentWindow) return;
            const message = event.data;
            if (!message || typeof message !== 'object') return;

            if (message.type === 'omnideck:download') {
                if (typeof message.url !== 'string' || message.url.length > 4096) return;
                if (typeof message.filename !== 'string' || message.filename.length > 255) return;
                if (message.filename && /[\\/\0]/.test(message.filename)) return;
                try {
                    const url = new URL(message.url, frameRef.current.src);
                    const appFiles = `/api/folder-apps/${encodeURIComponent(app.slug)}/frame/`;
                    if (url.origin !== window.location.origin || !url.pathname.startsWith(appFiles)) return;
                    const link = document.createElement('a');
                    link.href = url.href;
                    link.download = message.filename;
                    link.rel = 'noopener';
                    link.click();
                } catch {
                    // Ignore malformed or out-of-scope download URLs.
                }
                return;
            }
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
                    `/api/folder-apps/${encodeURIComponent(app.slug)}/invoke/${encodeURIComponent(message.action)}`,
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
            frameRef.current?.contentWindow?.postMessage(responseMessage, '*');
        };

        window.addEventListener('message', receiveMessage);
        return () => window.removeEventListener('message', receiveMessage);
    }, [app, onOpenChat, onComposeChat]);

    return (
        <div className={`${styles.frameWell} ${!active ? styles.hidden : ''}`}>
            <iframe
                key={`${app.slug}-${reloadSignal}`}
                ref={frameRef}
                className={styles.frame}
                src={`/api/folder-apps/${encodeURIComponent(app.slug)}/frame/`}
                title={app.title}
                sandbox="allow-scripts allow-downloads"
                data-testid="folder-app-frame"
            />
        </div>
    );
}
