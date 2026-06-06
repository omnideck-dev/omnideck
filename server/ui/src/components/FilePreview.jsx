import { useState, useEffect, useCallback } from 'react';
import styles from './FilePreview.module.css';
import FileIcon from './icons/FileIcon.jsx';
import ImageIcon from './icons/ImageIcon.jsx';
import DownloadIcon from './icons/DownloadIcon.jsx';
import ExpandIcon from './icons/ExpandIcon.jsx';
import CollapseIcon from './icons/CollapseIcon.jsx';
import SourceIcon from './icons/SourceIcon.jsx';
import EyeIcon from './icons/EyeIcon.jsx';
import CopyIcon from './icons/CopyIcon.jsx';
import RefreshIcon from './icons/RefreshIcon.jsx';
import FileContentRenderer from './FileContentRenderer.jsx';
import IconButton from './primitives/IconButton.jsx';
import useFileContent from '../hooks/useFileContent.js';

function getFileIcon(contentType, filename) {
    if (contentType?.startsWith('image/') || filename?.match(/\.(jpg|jpeg|png|gif|webp|svg)$/i)) {
        return <ImageIcon size={14} />;
    }
    if (contentType?.startsWith('text/') || filename?.match(/\.(js|jsx|ts|tsx|py|java|cpp|c|h|go|rs|rb|php|html|css|json|xml|yaml|yml|md|txt)$/i)) {
        return <SourceIcon size={14} />;
    }
    return <FileIcon size={14} />;
}

/**
 * A file preview, shown either inline in the preview panel or as a full-viewport
 * overlay. The two modes share one toolbar and renderer; `fullscreen` only swaps
 * the outer chrome (overlay + Esc + Back vs panel + Expand).
 */
export default function FilePreview({ item, fullscreen = false, onFullscreen, onClose }) {
    const {
        text,
        viewMode,
        setViewMode,
        isHtml,
        isMarkdown,
        showToggle,
        isImageFile,
        isPdf,
        pdfSrc,
        iframeSrc,
        imageSrc,
        handleDownload,
        handleCopy,
        canCopy,
        stale,
        refresh,
    } = useFileContent(item);

    const [copied, setCopied] = useState(false);
    const onCopyClick = async () => {
        const ok = await handleCopy();
        if (!ok) return;
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    // Esc leaves the fullscreen overlay; no-op for the inline tab.
    const handleKeyDown = useCallback((e) => {
        if (fullscreen && e.key === 'Escape' && onClose) onClose();
    }, [fullscreen, onClose]);
    useEffect(() => {
        if (!fullscreen) return undefined;
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [fullscreen, handleKeyDown]);

    const { filename, content_type } = item;
    const fileIcon = getFileIcon(content_type, filename);

    // The inline tab carries the e2e hooks; the overlay is queried by its own
    // container/back ids, so omit the per-control ids there to avoid duplicates.
    const t = (id) => (fullscreen ? undefined : id);

    return (
        <div
            className={fullscreen ? styles.fullscreen : styles.filePreview}
            data-testid={fullscreen ? 'fullscreen-preview' : undefined}
        >
            <div className={styles.toolbar}>
                <div className={styles.toolbarLeft}>
                    <div className={styles.filePill}>
                        <span className={styles.fileIcon}>{fileIcon}</span>
                        <span className={styles.fileName} title={filename}>
                            {filename || 'File'}
                        </span>
                    </div>
                </div>

                <div className={styles.toolbarCenter}>
                    {showToggle && !isPdf && (
                        <div className={styles.toggle} data-testid={t('file-view-toggle')}>
                            <button
                                className={`${styles.toggleBtn} ${viewMode === 'source' ? styles.toggleBtnActive : ''}`}
                                onClick={() => setViewMode('source')}
                                data-testid={t('file-view-source')}
                            >
                                <SourceIcon size={12} />
                                Source
                            </button>
                            <button
                                className={`${styles.toggleBtn} ${viewMode === 'preview' ? styles.toggleBtnActive : ''}`}
                                onClick={() => setViewMode('preview')}
                                data-testid={t('file-view-preview')}
                            >
                                <EyeIcon size={12} />
                                Preview
                            </button>
                        </div>
                    )}
                    {!showToggle && !isPdf && !isImageFile && (
                        <div className={styles.toggle} data-testid={t('file-view-source-only')}>
                            <button className={`${styles.toggleBtn} ${styles.toggleBtnActive}`}>
                                <SourceIcon size={12} /> Source
                            </button>
                        </div>
                    )}
                </div>

                <div className={styles.toolbarRight}>
                    {stale && (
                        <button
                            className={styles.refreshLink}
                            onClick={refresh}
                            title="File changed on disk — click to reload"
                            data-testid={t('file-refresh')}
                        >
                            <RefreshIcon size={12} />
                            Refresh
                        </button>
                    )}
                    {canCopy && (
                        <IconButton
                            size="sm"
                            onClick={onCopyClick}
                            title={copied ? 'Copied!' : 'Copy to clipboard'}
                            aria-label="Copy file contents to clipboard"
                            data-testid={t('file-copy')}
                        >
                            <CopyIcon size={14} />
                        </IconButton>
                    )}
                    <IconButton
                        size="sm"
                        onClick={handleDownload}
                        title="Download"
                        aria-label="Download file"
                        data-testid={t('file-download')}
                    >
                        <DownloadIcon size={14} />
                    </IconButton>
                    {fullscreen ? (
                        <IconButton
                            size="sm"
                            onClick={onClose}
                            title="Exit fullscreen"
                            aria-label="Exit fullscreen"
                            data-testid="fullscreen-back"
                        >
                            <CollapseIcon size={14} />
                        </IconButton>
                    ) : onFullscreen && (
                        <IconButton
                            size="sm"
                            onClick={onFullscreen}
                            title="Fullscreen"
                            aria-label="Open fullscreen"
                            data-testid="file-fullscreen"
                        >
                            <ExpandIcon size={14} />
                        </IconButton>
                    )}
                </div>
            </div>

            <div className={styles.content}>
                <FileContentRenderer
                    item={item}
                    viewMode={viewMode}
                    text={text}
                    isMarkdown={isMarkdown}
                    isHtml={isHtml}
                    isImageFile={isImageFile}
                    isPdf={isPdf}
                    iframeSrc={iframeSrc}
                    pdfSrc={pdfSrc}
                    imageSrc={imageSrc}
                    styles={styles}
                />
            </div>
        </div>
    );
}
