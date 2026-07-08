// Export/import helpers for agent-profile and skill bundles.
//
// Export is a plain GET the browser saves as a file — the server sends the
// bundle with a Content-Disposition attachment header. Import reads a picked
// file, checks it parses as JSON, and POSTs it to /api/import.

function triggerDownload(url) {
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    a.click();
}

export function downloadProfileBundle(id, { includeSkills = false, includeModel = true } = {}) {
    const params = new URLSearchParams({
        include_skills: includeSkills ? 'true' : 'false',
        include_model: includeModel ? 'true' : 'false',
    });
    triggerDownload(`/api/profiles/${encodeURIComponent(id)}/export?${params.toString()}`);
}

export function downloadSkillBundle(id) {
    triggerDownload(`/api/skills/${encodeURIComponent(id)}/export`);
}

/**
 * Read a picked bundle file and import it.
 * Returns { ok: true, data } or { ok: false, error } for the caller to toast.
 */
export async function importBundleFile(file) {
    let text;
    try {
        text = await file.text();
    } catch {
        return { ok: false, error: 'Could not read that file.' };
    }
    let payload;
    try {
        payload = JSON.parse(text);
    } catch {
        return { ok: false, error: 'That file is not a valid bundle (not JSON).' };
    }
    let res;
    try {
        res = await fetch('/api/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
    } catch {
        return { ok: false, error: 'Import request failed.' };
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, error: body.error || 'Import failed.' };
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
