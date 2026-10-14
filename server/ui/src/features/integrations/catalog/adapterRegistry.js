const GOOGLE_BASE_SCOPES = ['openid', 'email', 'profile'];
const GOOGLE_INTEGRATION_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/contacts.readonly',
];

const ADAPTERS = {
    icloud: {
        kind: 'app_password',
        icon: 'bi-apple',
        vendor: 'Apple',
        appPasswordUrl: 'https://account.apple.com/account/manage',
        appPasswordHost: 'account.apple.com',
        emailPlaceholder: 'you@icloud.com',
    },
    gmail: {
        kind: 'app_password',
        icon: 'bi-envelope-at',
        vendor: 'Google',
        appPasswordUrl: 'https://myaccount.google.com/apppasswords',
        appPasswordHost: 'myaccount.google.com',
        emailPlaceholder: 'you@gmail.com',
    },
    google_workspace: {
        kind: 'google_oauth',
        icon: 'bi-google',
        vendor: 'Google',
        emailPlaceholder: 'you@gmail.com',
        scopes: [...GOOGLE_BASE_SCOPES, ...GOOGLE_INTEGRATION_SCOPES],
    },
    http: {
        kind: 'http_token',
        icon: 'bi-plug',
        vendor: 'the API',
    },
    test: {
        kind: 'test',
        icon: 'bi-wrench-adjustable-circle',
        vendor: 'test broker',
    },
};

const FALLBACK_ADAPTER = {
    kind: 'unsupported',
    icon: 'bi-plug',
    vendor: 'this integration',
};

const UPDATE_COPY = {
    app_password: { updateAction: 'Update app password', updateTitle: 'Sign-in', updateDescription: 'Replace the app-specific password for this account.' },
    google_oauth: { updateAction: 'Sign in again', updateTitle: 'Sign-in', updateDescription: 'Refresh access to your Google account.' },
    http_token: { updateAction: 'Update token', updateTitle: 'API access', updateDescription: 'Replace the token and confirm your API connection details.' },
    test: { updateAction: 'Update test credential', updateTitle: 'Test credential', updateDescription: 'Replace the credential for this local test integration.' },
    unsupported: { updateAction: 'Update connection', updateTitle: 'Connection', updateDescription: 'Update the details used to connect this integration.' },
};

export function getConnectionAdapter(catalogId) {
    const adapter = ADAPTERS[catalogId] || FALLBACK_ADAPTER;
    return { ...adapter, ...UPDATE_COPY[adapter.kind] };
}

export function errorCopy(error, entry) {
    const adapter = getConnectionAdapter(entry?.id);
    const vendor = adapter.vendor || entry?.title || 'this provider';
    switch (error?.code) {
        case 'AUTH':
            return {
                title: `${vendor} rejected the credentials`,
                description: adapter.kind === 'app_password'
                    ? `Generate a fresh app password in ${vendor}, paste it again, and retry.`
                    : 'Double-check the credentials and try again.',
            };
        case 'UPSTREAM':
            return {
                title: `Couldn't reach ${vendor}`,
                description: 'Try again in a moment. If it keeps failing, check your network and the provider status.',
            };
        case 'NETWORK':
            return {
                title: 'Network error',
                description: error.message || 'Check your connection and try again.',
            };
        default:
            return {
                title: `Couldn't connect ${entry?.title || 'this integration'}`,
                description: error?.message || 'Check the connection details and try again.',
            };
    }
}

export function slugify(value) {
    return (value || '')
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 48);
}
