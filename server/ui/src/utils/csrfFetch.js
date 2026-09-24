const SAFE_METHODS = new Set(['GET', 'HEAD']);

function requestUrl(input, baseUrl) {
    const value = typeof input === 'string' || input instanceof URL ? input : input.url;
    return new URL(value, baseUrl);
}

export function csrfFetch(originalFetch, baseUrl = window.location.href) {
    const applicationOrigin = new URL(baseUrl).origin;
    return (input, init = {}) => {
        const inputMethod = typeof Request !== 'undefined' && input instanceof Request
            ? input.method
            : 'GET';
        const method = (init.method || inputMethod).toUpperCase();
        let url;
        try {
            url = requestUrl(input, baseUrl);
        } catch {
            return originalFetch(input, init);
        }
        if (SAFE_METHODS.has(method) || url.origin !== applicationOrigin) {
            return originalFetch(input, init);
        }

        const headers = new Headers(
            typeof Request !== 'undefined' && input instanceof Request ? input.headers : undefined,
        );
        new Headers(init.headers).forEach((value, name) => headers.set(name, value));
        headers.set('X-Requested-With', 'XMLHttpRequest');
        return originalFetch(input, { ...init, headers });
    };
}
