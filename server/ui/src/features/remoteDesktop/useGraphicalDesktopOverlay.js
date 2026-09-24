import { useCallback, useState } from 'react';

import { useToast } from '../../components/ToastProvider.jsx';

/**
 * Owns startup and overlay visibility for the optional remote graphical
 * desktop. It is intentionally separate from Desktop View placement.
 */
export default function useGraphicalDesktopOverlay() {
    const { addToast } = useToast();
    const [open, setOpen] = useState(false);

    const openOverlay = useCallback(async () => {
        if (open) return;
        try {
            const response = await fetch('/api/desktop/start', {
                method: 'POST',
            });
            const data = await response.json();
            if (data.running) {
                setOpen(true);
            } else {
                addToast(data.error || 'Desktop is not available', {
                    type: 'error',
                });
            }
        } catch {
            addToast('Could not reach the server', { type: 'error' });
        }
    }, [addToast, open]);

    const closeOverlay = useCallback(() => setOpen(false), []);
    return { open, openOverlay, closeOverlay };
}
