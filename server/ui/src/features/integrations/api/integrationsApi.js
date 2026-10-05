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

export async function listIntegrationConnections() {
    const body = await readJson(await fetch('/api/integrations'));
    if (!Array.isArray(body.connections)) {
        throw new Error('Invalid integration connection response.');
    }
    return body.connections.filter(
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

export async function updateIntegration(connectionId, updates) {
    return readJson(await fetch(`/api/integrations/${encodeURIComponent(connectionId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
    }));
}

export async function reconnectIntegration(connectionId, authBlob) {
    return readJson(await fetch(
        `/api/integrations/${encodeURIComponent(connectionId)}/reconnect`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auth_blob: authBlob }),
        },
    ));
}

export async function removeIntegration(connectionId) {
    const response = await fetch(`/api/integrations/${encodeURIComponent(connectionId)}`, {
        method: 'DELETE',
    });
    if (!response.ok) await readJson(response);
}

export async function startIntegrationOAuth(payload) {
    const prefix = ['mcp', 'slack'].includes(payload.slug) ? '/api/integrations/mcp/oauth' : '/api/integrations/oauth';
    return readJson(await fetch(`${prefix}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }));
}

export async function getMCPConnectionSettings(connectionId) {
    const query = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : '';
    return readJson(await fetch(`/api/integrations/mcp/connection-settings${query}`));
}

export async function getIntegrationOAuthStatus(state) {
    const prefix = oauthPrefix(state);
    return readJson(await fetch(
        `${prefix}/status/${encodeURIComponent(state)}`,
    ));
}

export async function cancelIntegrationOAuth(state) {
    const prefix = oauthPrefix(state);
    return readJson(await fetch(
        `${prefix}/status/${encodeURIComponent(state)}`,
        { method: 'DELETE' },
    ));
}

function oauthPrefix(state) {
    return state.startsWith('mcp_') ? '/api/integrations/mcp/oauth' : '/api/integrations/oauth';
}

export function integrationError(error, fallback = 'Request failed') {
    return {
        code: error?.code || 'NETWORK',
        message: error?.message || fallback,
    };
}
