import React, { useState, useEffect } from 'react';
import styles from './AttachmentChip.module.css';

const _CODE_EXT = new Set([
    'js', 'jsx', 'ts', 'tsx', 'py', 'go', 'rs', 'java', 'c', 'cpp', 'h',
    'css', 'html', 'json', 'sh', 'sql', 'yml', 'yaml', 'toml',
]);
const _DOC_EXT = new Set(['md', 'txt', 'doc', 'docx', 'rtf', 'csv']);
const _IMG_EXT = new Set([
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif', 'heic', 'heif', 'tiff',
]);

/** Lowercase extension (without the dot) from a filename, or '' if none. */
function _ext(filename) {
    const dot = filename ? filename.lastIndexOf('.') : -1;
    return dot > 0 ? filename.slice(dot + 1).toLowerCase() : '';
}

/** Pick an icon + colour tint + short label for a non-image attachment. */
function _fileKind(filename, contentType) {
    const ext = _ext(filename);
    let label = ext ? ext.toUpperCase() : '';
    if (!label && contentType) {
        // e.g. "application/pdf" -> "PDF", "text/plain" -> "PLAIN"
        label = (contentType.split('/')[1] || '').split(/[-+.;]/)[0].toUpperCase();
    }
    if (!label) label = 'FILE';
    if (ext === 'pdf') return { icon: 'bi-file-earmark-pdf', tint: styles.tintPdf, label };
    if (_IMG_EXT.has(ext) || contentType?.startsWith('image/')) {
        return { icon: 'bi-file-earmark-image', tint: styles.tintDoc, label };
    }
    if (_CODE_EXT.has(ext)) return { icon: 'bi-file-earmark-code', tint: styles.tintCode, label };
    if (_DOC_EXT.has(ext)) return { icon: 'bi-file-earmark-text', tint: styles.tintDoc, label };
    return { icon: 'bi-file-earmark', tint: styles.tintDoc, label };
}

function _formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Split a filename so the extension (plus a few characters before it) is
 * always visible while the middle collapses under the stem's ellipsis. Keeps
 * long names distinguishable — the tail carries the extension and any trailing
 * version/date suffix that a plain end-ellipsis would drop.
 */
function _splitName(filename) {
    const s = filename || '';
    const dot = s.lastIndexOf('.');
    const cut = dot > 0 ? Math.max(0, dot - 3) : Math.max(0, s.length - 4);
    return { stem: s.slice(0, cut), tail: s.slice(cut) };
}

/**
 * One attachment preview: a fixed-height card with a 36px tile on the left —
 * the image thumbnail for images, a type-tinted icon otherwise — plus the
 * filename and a `TYPE · size` line. `src` selects the image thumbnail;
 * `sizeBytes` is shown when known. Shared by the composer (with `onRemove`)
 * and sent chat messages (read-only). The full filename is on the card's
 * title for hover.
 */
export default function AttachmentChip({ src, filename, content_type, sizeBytes, onRemove }) {
    // A persisted image loads from its container path; if that file is gone on
    // resume the load 404s. Fall back to the type-icon card instead of a broken
    // image. Reset when the src changes so a fresh path gets another chance.
    const [imgFailed, setImgFailed] = useState(false);
    useEffect(() => { setImgFailed(false); }, [src]);

    const isImage = !!src && !imgFailed;
    const kind = _fileKind(filename, content_type);
    const meta = sizeBytes != null ? `${kind.label} · ${_formatSize(sizeBytes)}` : kind.label;
    const { stem, tail } = _splitName(filename);

    return (
        <div
            className={styles.card}
            data-testid={isImage ? undefined : 'attachment-file'}
            title={filename || undefined}
        >
            <span className={`${styles.tile} ${isImage ? '' : kind.tint}`}>
                {isImage ? (
                    <img
                        className={styles.thumb}
                        src={src}
                        alt={filename || 'attachment'}
                        data-testid="attachment-image"
                        onError={() => setImgFailed(true)}
                    />
                ) : (
                    <i className={`bi ${kind.icon}`} />
                )}
            </span>
            <span className={styles.meta}>
                <span className={styles.name}>
                    <span className={styles.nameStem}>{stem}</span>
                    {tail && <span className={styles.nameTail}>{tail}</span>}
                </span>
                <span className={styles.sub}>{meta}</span>
            </span>
            {onRemove && (
                <button
                    type="button"
                    className={styles.remove}
                    onClick={onRemove}
                    aria-label="Remove attachment"
                    title="Remove attachment"
                >
                    <i className="bi bi-x-lg" />
                </button>
            )}
        </div>
    );
}
