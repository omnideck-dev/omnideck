/** Convert a raw container filesystem path to its same-origin file URL. */
export function containerFileUrl(path) {
    return path.split('/').map(encodeURIComponent).join('/');
}
