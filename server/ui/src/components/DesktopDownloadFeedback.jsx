import { useEffect } from 'react';
import { useToast } from './ToastProvider.jsx';

export default function DesktopDownloadFeedback() {
    const { addToast } = useToast();

    useEffect(() => {
        const onDownload = (event) => {
            const filename = event.detail?.filename || 'file';
            if (event.detail?.success) {
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
        window.addEventListener('omnideck:download', onDownload);
        return () => window.removeEventListener('omnideck:download', onDownload);
    }, [addToast]);

    return null;
}
