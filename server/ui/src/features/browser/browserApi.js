export class BrowserRequestError extends Error {
    constructor(message, { status, details } = {}) {
        super(message);
        this.name = 'BrowserRequestError';
        this.status = status;
        this.details = details;
    }
}

async function responseJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new BrowserRequestError(data.error || 'Browser request failed', {
            status: response.status,
            details: data,
        });
    }
    return data;
}

export async function getBrowserSession() {
    return responseJson(await fetch('/api/browser/session'));
}

export async function loadBrowserSession(profileId) {
    return responseJson(await fetch('/api/browser/session/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_id: profileId }),
    }));
}

export async function listBrowserProfiles() {
    return responseJson(await fetch('/api/browser/profiles'));
}

export async function previewBrowserState(conversationId = null) {
    const path = conversationId
        ? `/api/browser/conversations/${encodeURIComponent(conversationId)}/preview`
        : '/api/browser/session/preview';
    return responseJson(await fetch(path, { cache: 'no-store' }));
}

export async function saveBrowserState({
    conversationId = null,
    profileId = null,
    name = '',
    icon = 'bi-globe2',
    assignToAgent = false,
    previewToken = null,
}) {
    const path = conversationId
        ? `/api/browser/conversations/${encodeURIComponent(conversationId)}/save`
        : '/api/browser/session/save';
    const data = await responseJson(await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            profile_id: profileId,
            name,
            icon,
            assign_to_agent: assignToAgent,
            preview_token: previewToken,
        }),
    }));
    return conversationId ? data : { profile: data, assigned_to_agent: false };
}

export async function updateBrowserProfile(id, updates) {
    const profile = await responseJson(await fetch(`/api/browser/profiles/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
    }));
    return profile;
}

export async function deleteBrowserProfile(id) {
    const response = await fetch(`/api/browser/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (response.status === 204) {
        return;
    }
    await responseJson(response);
}

export async function removeBrowserProfileSites(id, domains) {
    const profile = await responseJson(await fetch(`/api/browser/profiles/${encodeURIComponent(id)}/sites`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domains }),
    }));
    return profile;
}

export async function clearBrowserProfileState(id) {
    const profile = await responseJson(await fetch(`/api/browser/profiles/${encodeURIComponent(id)}/state`, {
        method: 'DELETE',
    }));
    return profile;
}
