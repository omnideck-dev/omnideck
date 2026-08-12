// Export/import helpers for agent-profile and skill packs.
//
// Export is a plain GET the browser saves as a file — the server sends the
// pack with a Content-Disposition attachment header. Import uploads the
// picked file's bytes to /api/pack/import untouched; the server owns parsing
// and validation, so this stays correct for pack formats that aren't text.

// Save the file at `url` without leaving the app. Export is a plain GET that
// responds with a Content-Disposition attachment, so a synthetic <a> click lets
// the browser download it in place — unlike setting window.location, which would
// navigate the SPA away, or fetch(), which can't write a file to disk.
function triggerDownload(url) {
    const a = document.createElement('a');
    a.href = url;
    // Content-Disposition is sufficient in a normal browser, but native
    // webviews do not consistently promote a same-origin JSON navigation to a
    // host download. The download attribute tells WebKit/WKWebView/WebView2 to
    // enter their download path instead of replacing the hosted application.
    a.download = '';
    a.rel = 'noopener';
    // Some browsers only honor a programmatic download click when the anchor
    // is in the document, so attach it briefly.
    document.body.appendChild(a);
    a.click();
    a.remove();
}

export function downloadProfilePack(id, { includeSkills = false, includeModel = true } = {}) {
    const params = new URLSearchParams({
        include_skills: includeSkills ? 'true' : 'false',
        include_model: includeModel ? 'true' : 'false',
    });
    triggerDownload(`/api/pack/export/profiles/${encodeURIComponent(id)}?${params.toString()}`);
}

export function downloadSkillPack(id) {
    triggerDownload(`/api/pack/export/skills/${encodeURIComponent(id)}`);
}

/**
 * Upload a picked pack file to be imported.
 * Returns { ok: true, data } or { ok: false, error } for the caller to toast.
 */
export async function importPackFile(file) {
    let res;
    try {
        res = await fetch('/api/pack/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: file,
        });
    } catch {
        return { ok: false, error: 'Import request failed.' };
    }
    const body = await res.json().catch(() => null);
    if (!res.ok) return { ok: false, error: (body && body.error) || 'Import failed.' };
    // A 2xx with an unreadable or non-object body means the server didn't report
    // what it created, so treat it as a failure rather than a green toast that
    // silently claims nothing was imported.
    if (!body || typeof body !== 'object') return { ok: false, error: 'Import failed.' };
    return { ok: true, data: body };
}

/** Human-readable summary of what an import created, for a toast. */
export function importSummaryText(data) {
    const np = (data.profiles || []).length;
    const ns = (data.skills || []).length;
    const parts = [];
    if (np) parts.push(`${np} agent${np === 1 ? '' : 's'}`);
    if (ns) parts.push(`${ns} skill${ns === 1 ? '' : 's'}`);
    return parts.length ? `Imported ${parts.join(' and ')}.` : 'Nothing to import.';
}
