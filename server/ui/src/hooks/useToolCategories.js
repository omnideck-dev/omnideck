import { useEffect, useState } from 'react';

/** Refresh labels and approvals without replacing the editor's selections. */
export default function useToolCategories() {
    const [categories, setCategories] = useState([]);
    useEffect(() => {
        let active = true;
        let pending = false;
        const controller = new AbortController();
        const refresh = async () => {
            if (pending) return;
            pending = true;
            try {
                const response = await fetch('/api/tool-categories', { signal: controller.signal });
                if (!response.ok) throw new Error('Catalog unavailable');
                const data = await response.json();
                if (active) setCategories(Array.isArray(data) ? data : []);
            } catch {
                if (active) setCategories([]);
            } finally { pending = false; }
        };
        refresh();
        const timer = setInterval(refresh, 15000);
        window.addEventListener('focus', refresh);
        window.addEventListener('integrations-changed', refresh);
        return () => {
            active = false;
            controller.abort();
            clearInterval(timer);
            window.removeEventListener('focus', refresh);
            window.removeEventListener('integrations-changed', refresh);
        };
    }, []);
    return categories;
}
