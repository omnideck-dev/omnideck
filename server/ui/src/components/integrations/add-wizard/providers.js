export const PROVIDERS = [
    {
        slug: 'icloud',
        authFlow: 'app_password',
        category: 'Email & Calendar',
        title: 'iCloud',
        description: 'Email and calendar',
        icon: 'bi-envelope-at',
        vendor: 'Apple',
        appPasswordUrl: 'https://account.apple.com/account/manage',
        appPasswordHost: 'account.apple.com',
        emailPlaceholder: 'you@icloud.com',
        capabilities: ['email', 'calendar'],
    },
    {
        slug: 'gmail',
        authFlow: 'app_password',
        category: 'Email & Calendar',
        title: 'Gmail',
        description: 'Email',
        icon: 'bi-envelope-at',
        vendor: 'Google',
        appPasswordUrl: 'https://myaccount.google.com/apppasswords',
        appPasswordHost: 'myaccount.google.com',
        emailPlaceholder: 'you@gmail.com',
        capabilities: ['email'],
    },
    {
        slug: 'google_workspace',
        authFlow: 'oauth_device',
        category: 'Productivity Suites',
        title: 'Google Workspace',
        description: 'Mail, Calendar, Drive, Contacts',
        icon: 'bi-google',
        vendor: 'Google',
        capabilityGroups: [
            {
                id: 'email',
                label: 'Gmail',
                description: 'Messages, search, attachments',
                readScopes: ['https://www.googleapis.com/auth/gmail.readonly'],
                writeScopes: ['https://www.googleapis.com/auth/gmail.modify'],
                defaultAccess: 'rw',
            },
            {
                id: 'calendar',
                label: 'Calendar',
                description: 'Events, scheduling',
                readScopes: ['https://www.googleapis.com/auth/calendar.readonly'],
                writeScopes: ['https://www.googleapis.com/auth/calendar.events'],
                defaultAccess: 'rw',
            },
            {
                id: 'drive',
                label: 'Drive',
                description: 'Files, folders, documents',
                readScopes: ['https://www.googleapis.com/auth/drive.readonly'],
                writeScopes: ['https://www.googleapis.com/auth/drive.file'],
                defaultAccess: 'rw',
            },
            {
                id: 'contacts',
                label: 'Contacts',
                description: 'Names, emails, phone numbers',
                readScopes: ['https://www.googleapis.com/auth/contacts.readonly'],
                writeScopes: [],
                defaultAccess: 'r',
            },
        ],
        baseScopes: ['openid', 'email', 'profile'],
    },
    {
        slug: 'http',
        authFlow: 'token',
        category: 'Custom',
        title: 'HTTP API',
        description: 'Any REST endpoint with a token',
        icon: 'bi-plug',
        vendor: 'the API',
        capabilities: ['http'],
    },
    {
        slug: 'cli',
        authFlow: 'cli_env',
        category: 'CLI Tools',
        title: 'CLI Command',
        description: 'Run a script or CLI tool with secrets in its environment',
        icon: 'bi-terminal',
        vendor: 'your command',
        capabilities: ['cli'],
    },
];

export function errorCopy(error, provider) {
    const vendor = provider?.vendor ?? provider?.title ?? 'this provider';
    const isOauth = provider?.authFlow === 'oauth_device';
    const isToken = provider?.authFlow === 'token';
    const isCli = provider?.authFlow === 'cli_env';
    switch (error?.code) {
        case 'AUTH':
            if (isToken) {
                return {
                    title: 'The endpoint rejected the token',
                    description:
                        'The base URL responded but refused the token. Double-check '
                        + 'the token value and that the header name and template match '
                        + 'what the API expects.',
                };
            }
            if (isCli) {
                return {
                    title: `${vendor} rejected the credential`,
                    description:
                        'The command started but the credential was refused. Double-check '
                        + 'the value and try again.',
                };
            }
            if (isOauth) {
                return {
                    title: `${vendor} rejected the OAuth client`,
                    description:
                        'Double-check the Client ID and Client Secret you pasted. '
                        + 'Other common causes: the OAuth client type isn\'t "Desktop app", '
                        + 'or the app hasn\'t been published '
                        + '(Google Auth Platform → Audience → Publish app).',
                };
            }
            return {
                title: `${vendor} rejected the password`,
                description:
                    'App-specific passwords sometimes get revoked or mistyped. ' +
                    `Generate a fresh one in ${vendor}, paste it again, and retry.`,
            };
        case 'UPSTREAM':
            return {
                title: `Couldn't reach ${vendor}`,
                description:
                    'The server returned an error or timed out. Try again in a moment — ' +
                    'if it keeps failing, check your network or the provider\'s status page.',
            };
        case 'BAD_REQUEST':
            return {
                title: 'Couldn\'t add this integration',
                description: error.message || 'The request was rejected. Double-check your inputs.',
            };
        case 'NETWORK':
            return {
                title: 'Network error',
                description: error.message || 'Check your connection and try again.',
            };
        default:
            return {
                title: 'Couldn\'t add this integration',
                description: error?.message || 'Try again, or refresh and start over.',
            };
    }
}

export function slugifyEmail(email) {
    if (!email) return '';
    const local = email.split('@')[0].toLowerCase();
    return local.replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48);
}

// Token integrations have no email to derive an ID from, so the label
// becomes the user-suffix. Same sanitizer rules as slugifyEmail.
export function slugifyLabel(label) {
    if (!label) return '';
    return label.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48);
}

// Splits a cli integration's "Command" field into argv. A plain `.split(/\s+/)`
// would break a binary/script path containing a space (e.g. a bind-mounted
// "My Scripts/run.sh"), so this understands single- and double-quoted
// segments — not full shell syntax (no escaping inside quotes), just enough
// to let a user quote one path with spaces.
//
// Throws on an odd number of either quote character rather than silently
// falling back to matching the stray quote as a literal token — without
// this, a typo like `foo "bar` (missing closing quote) would produce
// `["foo", "\"bar"]` and the broker would then fail to exec a binary
// literally named `"bar`, a confusing error far from the actual mistake.
export function splitCommand(raw) {
    const doubleQuotes = (raw.match(/"/g) || []).length;
    const singleQuotes = (raw.match(/'/g) || []).length;
    if (doubleQuotes % 2 !== 0 || singleQuotes % 2 !== 0) {
        throw new Error('Unbalanced quote in command — check your quote marks.');
    }
    const tokens = [];
    const pattern = /"([^"]*)"|'([^']*)'|(\S+)/g;
    let match = pattern.exec(raw);
    while (match !== null) {
        const token = match[1] ?? match[2] ?? match[3];
        if (token) tokens.push(token);
        match = pattern.exec(raw);
    }
    return tokens;
}

// Canonical form for a CLI integration's folder scope: strips leading and
// trailing slashes, same as the broker applies before enforcing it, so
// "repo", "/repo", and "/repo/" are all recognized as the same scope. A
// value that's only slashes (or blank) normalizes to '' — callers treat
// that as "not actually filled in," not as "global."
export function normalizePathPrefix(raw) {
    return raw.trim().replace(/^\/+|\/+$/g, '');
}

// Shared shape-builder for a cli integration's auth_blob, used by both the
// add wizard and the detail pane's "Replace secret" form — keeping the
// command-splitting / vars-to-dict logic in one place instead of two copies
// that can drift out of sync. `pathPrefix` is the already-resolved value
// (normalized string or null) — each caller resolves its own scope input
// shape (a global/folder toggle in the wizard, a fixed existing value in
// the replace-secret form) before calling this.
export function buildCliAuthBlob({ command, vars, pathPrefix }) {
    return {
        command: splitCommand(command.trim()),
        vars: Object.fromEntries(
            vars.filter(v => v.name.trim()).map(v => [v.name.trim(), v.value]),
        ),
        path_prefix: pathPrefix,
    };
}
