import { containerFileUrl } from '../utils/containerFileUrl.js';
import styles from './FileOutput.module.css';
import { canPreviewFile } from '../utils/fileTypes.js';
import FileIcon from './icons/FileIcon.jsx';
import ImageIcon from './icons/ImageIcon.jsx';
import SourceIcon from './icons/SourceIcon.jsx';
import DownloadIcon from './icons/DownloadIcon.jsx';
import EyeIcon from './icons/EyeIcon.jsx';
import { base64Bytes, bytesDownload, triggerDownload } from '../utils/downloads.js';
import { useFileControls } from './FileControls.jsx';

function FileOutputIcon({ contentType, filename }) {
    if (contentType?.startsWith('image/') || filename?.match(/\.(jpg|jpeg|png|gif|webp|svg)$/i)) {
        return <ImageIcon size={16} />;
    }
    if (contentType?.startsWith('text/') || filename?.match(/\.(js|jsx|ts|tsx|py|java|cpp|c|h|go|rs|rb|php|html|css|json|xml|yaml|yml|md|txt)$/i)) {
        return <SourceIcon size={16} />;
    }
    return <FileIcon size={16} />;
}

function openOrDownload({ item, previewable, onPreview, download }) {
    if (previewable && onPreview) onPreview(item);
    else download();
}

function FileCardActions({ item, previewable, onPreview, download }) {
    return (
        <div className={styles.fileOutputBtns}>
            {previewable && onPreview && (
                <button
                    className={styles.fileOutputBtn}
                    onClick={(e) => { e.stopPropagation(); onPreview(item); }}
                    data-testid="file-preview-btn"
                >
                    <EyeIcon size={12} />
                    Preview
                </button>
            )}
            <button
                className={styles.fileOutputBtn}
                onClick={(e) => { e.stopPropagation(); download(); }}
                data-testid="file-download-btn"
            >
                <DownloadIcon size={12} />
                Download
            </button>
        </div>
    );
}

const DESKTOP_CARD = { Actions: FileCardActions, open: openOrDownload };

export default function FileOutput({ item, onPreview }) {
    const { filename, content_type, content, path } = item;
    const previewable = canPreviewFile(content_type, filename);
    const { Actions, open } = useFileControls()?.card ?? DESKTOP_CARD;

    const download = () => {
        if (path) {
            triggerDownload(containerFileUrl(path), filename);
            return;
        }
        bytesDownload(base64Bytes(content), content_type, filename);
    };

    const slot = { item, previewable, onPreview, download };

    return (
        <div className={styles.fileOutput} onClick={() => open(slot)} style={{ cursor: 'pointer' }}>
            <div className={styles.fileOutputHeader}>
                <span className={styles.fileOutputIcon}>
                    <FileOutputIcon contentType={content_type} filename={filename} />
                </span>
                <div className={styles.fileOutputInfo}>
                    <span className={styles.fileOutputName}>{filename}</span>
                    <span className={styles.fileOutputMime}>{content_type}</span>
                </div>
                {Actions && <Actions {...slot} />}
            </div>
        </div>
    );
}
