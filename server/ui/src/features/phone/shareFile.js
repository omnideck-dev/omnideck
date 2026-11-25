import { containerFileUrl } from '../../utils/containerFileUrl.js';
import { base64Bytes } from '../../utils/downloads.js';

async function fileFromItem(item) {
    const filename = item.filename || 'file';
    const type = item.content_type || 'application/octet-stream';
    if (item.path) {
        const response = await fetch(containerFileUrl(item.path));
        if (!response.ok) throw new Error('The file could not be loaded.');
        return new File([await response.blob()], filename, { type });
    }
    return new File([base64Bytes(item.content || '')], filename, { type });
}

export function canShareFiles() {
    return typeof navigator.canShare === 'function' && typeof navigator.share === 'function';
}

export async function shareFile(item) {
    const file = await fileFromItem(item);
    if (!navigator.canShare({ files: [file] })) throw new Error('This file type can\'t be shared.');
    try {
        await navigator.share({ files: [file], title: file.name });
        return true;
    } catch (error) {
        if (error?.name === 'AbortError') return false;
        throw error;
    }
}
