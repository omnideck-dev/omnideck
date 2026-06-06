import { useState, useMemo, useEffect, useCallback } from 'react';
import { hasPreviewToggle, isImageFile, isPdfFile } from '../utils/fileTypes.js';
import copyToClipboard from '../utils/copyToClipboard.js';

// How often to re-check a disk-backed file for changes while its preview is open.
const POLL_INTERVAL_MS = 4000;

function _decodeText(b64) {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
}

// Append a cache-busting marker so the browser refetches an updated file
// rather than serving the stale bytes it already has for this URL.
function _bust(url, nonce) {
    if (!nonce || !url) return url;
    return `${url}${url.includes('?') ? '&' : '?'}v=${nonce}`;
}

export default function useFileContent(item) {
    const { filename, content_type, content, path } = item || {};

    const [fetchedText, setFetchedText] = useState(null);
    const [stale, setStale] = useState(false);
    const [reloadNonce, setReloadNonce] = useState(0);
    const [viewMode, setViewMode] = useState(() =>
        hasPreviewToggle(content_type, filename) ? 'preview' : 'source'
    );

    const itemKey = path || content;
    useEffect(() => {
        setFetchedText(null);
        setStale(false);
        setReloadNonce(0);
        setViewMode(hasPreviewToggle(content_type, filename) ? 'preview' : 'source');
    }, [itemKey, content_type, filename]);

    const isImage = isImageFile(content_type, filename);
    const isPdf = isPdfFile(content_type, filename);
    const isHtml = content_type === 'text/html';
    const isMarkdown =
        content_type === 'text/markdown' ||
        content_type === 'text/x-markdown' ||
        (!isHtml && filename && (filename.endsWith('.md') || filename.endsWith('.mdx')));
    const showToggle = isHtml || isMarkdown;

    const text = useMemo(() => {
        // Don't decode binary content (images, PDFs) as text
        if (isImage || isPdf) return null;
        if (content) return _decodeText(content);
        return fetchedText;
    }, [content, fetchedText, isImage, isPdf]);

    // Fetch remote text content (not for images or PDFs). Re-runs on refresh.
    useEffect(() => {
        if (isImage || isPdf || content || !path) return;
        let cancelled = false;
        fetch(_bust(path, reloadNonce)).then(r => {
            if (!r.ok) throw new Error(`Failed to load ${path}: ${r.status}`);
            return r.text();
        }).then(t => {
            if (!cancelled) setFetchedText(t);
        }).catch(err => {
            if (!cancelled) setFetchedText(`Error loading file: ${err.message}`);
        });
        return () => { cancelled = true; };
    }, [content, path, isImage, isPdf, reloadNonce]);

    // Watch the disk-backed file for changes, independent of how it's rendered.
    // Inline (base64) content has no disk backing, so there's nothing to watch.
    // Idles while the tab is hidden; tears down on unmount or file switch.
    const refresh = useCallback(() => {
        setStale(false);
        setReloadNonce(n => n + 1);
    }, []);

    useEffect(() => {
        if (content || !path) return;
        let cancelled = false;
        let baseline = null;

        const probe = async () => {
            const r = await fetch(path, { method: 'HEAD' });
            return r.headers.get('ETag') || r.headers.get('Last-Modified');
        };

        probe().then(v => { if (!cancelled) baseline = v; }).catch(() => {});

        const check = async () => {
            if (document.hidden || baseline == null) return;
            try {
                const v = await probe();
                if (!cancelled && v && v !== baseline) setStale(true);
            } catch { /* transient network blip — retry next tick */ }
        };
        const timer = setInterval(check, POLL_INTERVAL_MS);
        // Catch up immediately when the user returns to the tab.
        const onVisible = () => { if (!document.hidden) check(); };
        document.addEventListener('visibilitychange', onVisible);

        return () => {
            cancelled = true;
            clearInterval(timer);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [content, path, reloadNonce]);

    // Blob URL for HTML iframe preview
    const iframeSrc = useMemo(() => {
        if (isHtml && path) return _bust(path, reloadNonce);
        if (isHtml && text) {
            const blob = new Blob([text], { type: 'text/html' });
            return URL.createObjectURL(blob);
        }
        return null;
    }, [isHtml, path, text, reloadNonce]);

    // Blob/path URL for PDF preview
    const pdfSrc = useMemo(() => {
        if (!isPdf) return null;
        if (path) return _bust(path, reloadNonce);
        if (content) {
            const byteChars = atob(content);
            const bytes = new Uint8Array(byteChars.length);
            for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i);
            const blob = new Blob([bytes], { type: 'application/pdf' });
            return URL.createObjectURL(blob);
        }
        return null;
    }, [isPdf, path, content, reloadNonce]);

    // Path URL for image preview (inline base64 content takes precedence).
    const imageSrc = useMemo(() => {
        if (!isImage || content || !path) return null;
        return _bust(path, reloadNonce);
    }, [isImage, content, path, reloadNonce]);

    useEffect(() => {
        return () => {
            if (iframeSrc && iframeSrc.startsWith('blob:')) URL.revokeObjectURL(iframeSrc);
            if (pdfSrc && pdfSrc.startsWith('blob:')) URL.revokeObjectURL(pdfSrc);
        };
    }, [iframeSrc, pdfSrc]);

    const canCopy = !isImage && !isPdf && !!text;

    const handleCopy = useCallback(async () => {
        if (!text) return false;
        return copyToClipboard(text);
    }, [text]);

    const handleDownload = useCallback(() => {
        const link = document.createElement('a');
        if (text) {
            const blob = new Blob([text], { type: content_type || 'text/plain' });
            link.href = URL.createObjectURL(blob);
        } else if (path) {
            link.href = path;
        } else if (content) {
            const byteChars = atob(content);
            const bytes = new Uint8Array(byteChars.length);
            for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i);
            const blob = new Blob([bytes], { type: content_type || 'application/octet-stream' });
            link.href = URL.createObjectURL(blob);
        }
        link.download = filename || 'file';
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 100);
    }, [text, content, content_type, path, filename]);

    return {
        text,
        viewMode,
        setViewMode,
        isHtml,
        isMarkdown,
        showToggle,
        isImageFile: isImage,
        isPdf,
        pdfSrc,
        iframeSrc,
        imageSrc,
        handleDownload,
        handleCopy,
        canCopy,
        stale,
        refresh,
    };
}
