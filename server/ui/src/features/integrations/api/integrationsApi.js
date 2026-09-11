async function readJson(response) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = body?.error;
        const message = typeof error === 'string'
            ? error
            : error?.message || `HTTP ${response.status}`;
        const requestError = new Error(message);
        requestError.code = error?.code || 'ERROR';
        throw requestError;
    }
    return body;
}

export async function listIntegrations() {
    const body = await readJson(await fetch('/api/integrations'));
    return (body.integrations || []).filter(
        connection => connection.kind !== 'model_provider',
    );
}

export async function listIntegrationCatalog() {
    const body = await readJson(await fetch('/api/integrations/catalog'));
    return body.integrations || [];
}

export async function createIntegration(payload) {
    return readJson(await fetch('/api/integrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }));
}

export async function updateIntegration(integrationId, updates) {
    return readJson(await fetch(`/api/integrations/${encodeURIComponent(integrationId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
    }));
}

export async function reconnectIntegration(integrationId, authBlob) {
    return readJson(await fetch(
        `/api/integrations/${encodeURIComponent(integrationId)}/reconnect`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auth_blob: authBlob }),
        },
    ));
}

export async function removeIntegration(integrationId) {
    const response = await fetch(`/api/integrations/${encodeURIComponent(integrationId)}`, {
        method: 'DELETE',
    });
    if (!response.ok) await readJson(response);
}

export async function startIntegrationOAuth(payload) {
    return readJson(await fetch('/api/integrations/oauth/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }));
}

export async function getIntegrationOAuthStatus(state) {
    return readJson(await fetch(
        `/api/integrations/oauth/status/${encodeURIComponent(state)}`,
    ));
}

export async function cancelIntegrationOAuth(state) {
    return readJson(await fetch(
        `/api/integrations/oauth/status/${encodeURIComponent(state)}`,
        { method: 'DELETE' },
    ));
}

export function integrationError(error, fallback = 'Request failed') {
    return {
        code: error?.code || 'NETWORK',
        message: error?.message || fallback,
    };
}
