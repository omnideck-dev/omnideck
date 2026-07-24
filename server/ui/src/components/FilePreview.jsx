import { useState, useEffect } from 'react';
import styles from './FilePreview.module.css';
import FileIcon from './icons/FileIcon.jsx';
import ImageIcon from './icons/ImageIcon.jsx';
import DownloadIcon from './icons/DownloadIcon.jsx';
import SourceIcon from './icons/SourceIcon.jsx';
import EyeIcon from './icons/EyeIcon.jsx';
import CopyIcon from './icons/CopyIcon.jsx';
import SaveIcon from './icons/SaveIcon.jsx';
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
 * A file preview rendered inside its stable artifact tab.
 * Full-screen presentation belongs to the desktop window manager.
 */
export default function FilePreview({ item }) {
    const {
        text,
        draft,
        setDraft,
        isDirty,
        canSave,
        save,
        saving,
        saveError,
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

    // Cmd/Ctrl+S saves the source edits, matching editor muscle memory.
    useEffect(() => {
        if (!canSave) return undefined;
        const onSaveKey = (e) => {
            if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
                e.preventDefault();
                if (isDirty && !saving) save();
            }
        };
        document.addEventListener('keydown', onSaveKey);
        return () => document.removeEventListener('keydown', onSaveKey);
    }, [canSave, isDirty, saving, save]);

    const { filename, content_type } = item;
    const fileIcon = getFileIcon(content_type, filename);

    return (
        <div className={styles.filePreview}>
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
                        <div className={styles.toggle} data-testid="file-view-toggle">
                            <button
                                className={`${styles.toggleBtn} ${viewMode === 'source' ? styles.toggleBtnActive : ''}`}
                                onClick={() => setViewMode('source')}
                                data-testid="file-view-source"
                            >
                                <SourceIcon size={12} />
                                Source
                            </button>
                            <button
                                className={`${styles.toggleBtn} ${viewMode === 'preview' ? styles.toggleBtnActive : ''}`}
                                onClick={() => setViewMode('preview')}
                                data-testid="file-view-preview"
                            >
                                <EyeIcon size={12} />
                                Preview
                            </button>
                        </div>
                    )}
                    {!showToggle && !isPdf && !isImageFile && (
                        <div className={styles.toggle} data-testid="file-view-source-only">
                            <button className={`${styles.toggleBtn} ${styles.toggleBtnActive}`}>
                                <SourceIcon size={12} /> Source
                            </button>
                        </div>
                    )}
                </div>

                <div className={styles.toolbarRight}>
                    {canSave && viewMode === 'source' && (
                        <IconButton
                            size="sm"
                            onClick={save}
                            disabled={!isDirty || saving}
                            title={saveError ? `Save failed: ${saveError}` : saving ? 'Saving…' : isDirty ? 'Save (⌘S)' : 'Saved'}
                            aria-label="Save file"
                            data-testid="file-save"
                        >
                            <SaveIcon size={14} className={isDirty ? styles.saveIconDirty : undefined} />
                        </IconButton>
                    )}
                    {stale && (
                        <button
                            className={styles.refreshLink}
                            onClick={refresh}
                            title="File changed on disk — click to reload"
                            data-testid="file-refresh"
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
                            data-testid="file-copy"
                        >
                            <CopyIcon size={14} />
                        </IconButton>
                    )}
                    <IconButton
                        size="sm"
                        onClick={handleDownload}
                        title="Download"
                        aria-label="Download file"
                        data-testid="file-download"
                    >
                        <DownloadIcon size={14} />
                    </IconButton>
                </div>
            </div>

            <div className={styles.content}>
                <FileContentRenderer
                    item={item}
                    viewMode={viewMode}
                    text={text}
                    draft={draft}
                    onDraftChange={setDraft}
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
