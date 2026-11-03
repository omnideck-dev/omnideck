import { useEffect, useRef, useState } from 'react';

/** Fetch only the saved reasoning entries in an expanded activity section. */
export default function useSavedThinking(references, enabled) {
    const key = JSON.stringify(references);
    const cache = useRef(null);
    const [result, setResult] = useState(null);
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        if (!enabled || key === '[]' || cache.current?.key === key) return;
        const controller = new AbortController();
        setResult(null);
        const refs = JSON.parse(key);
        const groups = new Map();
        for (const ref of refs) {
            if (!groups.has(ref.conversationId)) groups.set(ref.conversationId, new Set());
            groups.get(ref.conversationId).add(ref.eventId);
        }
        async function load() {
            try {
                const data = {};
                await Promise.all([...groups].map(async ([conversationId, ids]) => {
                    const response = await fetch(
                        `/api/conversations/sessions/${encodeURIComponent(conversationId)}/thinking`,
                        {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ event_ids: [...ids] }),
                            signal: controller.signal,
                        },
                    );
                    if (!response.ok) throw new Error('Could not load saved thinking');
                    const thinking = await response.json();
                    for (const id of ids) {
                        if (typeof thinking[id] !== 'string') throw new Error('Missing saved thinking');
                        data[`${conversationId}/${id}`] = thinking[id];
                    }
                }));
                if (controller.signal.aborted) return;
                cache.current = { key, data };
                setResult({ key, data });
            } catch {
                if (!controller.signal.aborted) setResult({ key, error: true });
            }
        }
        void load();
        return () => controller.abort();
    }, [key, enabled, attempt]);

    const current = result?.key === key ? result : null;
    return {
        loading: enabled && references.length > 0 && !current,
        error: Boolean(current?.error),
        text: (ref) => current?.data?.[`${ref.conversationId}/${ref.eventId}`] || '',
        retry: () => { setResult(null); setAttempt((value) => value + 1); },
    };
}
