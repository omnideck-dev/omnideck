/**
 * Start a browser/native-webview download without navigating the application.
 * Keeping the anchor in the document through the click is required by WebKit
 * hosts, and delaying blob revocation gives the native download handler time to
 * claim the bytes.
 */
export function triggerDownload(url, filename = '') {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
    if (String(url).startsWith('blob:')) {
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
}

export function bytesDownload(content, contentType, filename) {
    const blob = new Blob([content], { type: contentType || 'application/octet-stream' });
    triggerDownload(URL.createObjectURL(blob), filename);
}

export function base64Bytes(content) {
    const chars = atob(content);
    const bytes = new Uint8Array(chars.length);
    for (let i = 0; i < chars.length; i++) bytes[i] = chars.charCodeAt(i);
    return bytes;
}
