import { useState } from 'react';

import FileDownloadButton from '../../components/FileDownloadButton.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import { useToast } from '../../components/ToastProvider.jsx';
import { canShareFiles, shareFile } from './shareFile.js';

export default function PhoneFileAction({ item, download }) {
    const { addToast } = useToast();
    const [sharing, setSharing] = useState(false);

    if (!canShareFiles()) return <FileDownloadButton download={download} />;

    const share = async (e) => {
        e.stopPropagation();
        setSharing(true);
        try {
            await shareFile(item);
        } catch (error) {
            addToast(error?.message || 'The file could not be shared.', { type: 'error' });
        } finally {
            setSharing(false);
        }
    };

    return (
        <IconButton
            size="sm"
            onClick={share}
            disabled={sharing}
            title="Share"
            aria-label="Share file"
            data-testid="phone-file-share"
        >
            <i className="bi bi-box-arrow-up" aria-hidden="true" />
        </IconButton>
    );
}
