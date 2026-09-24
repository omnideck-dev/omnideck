import { useEffect } from 'react';
import { useToast } from './ToastProvider.jsx';

export default function DesktopDownloadFeedback() {
    const { addToast } = useToast();

    useEffect(() => {
        const showDownload = (detail) => {
            if (window.__omnideckPendingDownload === detail) {
                delete window.__omnideckPendingDownload;
            }
            const filename = detail?.filename || 'file';
            if (detail?.success) {
                addToast(`${filename} was saved to Downloads.`, {
                    type: 'success',
                    title: 'Download complete',
                });
            } else {
                addToast(`Could not save ${filename}.`, {
                    type: 'error',
                    title: 'Download failed',
                });
            }
        };
        const onDownload = (event) => showDownload(event.detail);
        window.addEventListener('omnideck:download', onDownload);
        if (window.__omnideckPendingDownload) {
            showDownload(window.__omnideckPendingDownload);
        }
        return () => window.removeEventListener('omnideck:download', onDownload);
    }, [addToast]);

    return null;
}
