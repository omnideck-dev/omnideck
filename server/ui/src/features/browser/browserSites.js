import psl from 'psl';

function normalizedDomain(value) {
    return String(value || '').trim().replace(/^\.+|\.+$/g, '').toLocaleLowerCase();
}

export function registrableDomain(value) {
    const domain = normalizedDomain(value);
    if (!domain) return '';
    if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(domain) || domain.includes(':')) return domain;
    return psl.get(domain) || domain;
}

/**
 * Collapse origin-level storage summaries into the sites people recognize.
 * This changes presentation only; the saved browser state retains every origin.
 */
export function groupBrowserSites(sites = []) {
    const groups = new Map();

    sites.forEach((site) => {
        const domain = normalizedDomain(site.domain);
        if (!domain) return;
        const baseDomain = registrableDomain(domain);
        const current = groups.get(baseDomain) || {
            domain: baseDomain,
            domains: [],
            cookies: 0,
            local_storage: false,
            indexed_db: false,
        };

        current.domains.push(domain);
        current.cookies += Number(site.cookies) || 0;
        current.local_storage ||= !!site.local_storage;
        current.indexed_db ||= !!site.indexed_db;
        groups.set(baseDomain, current);
    });

    return [...groups.values()]
        .map((site) => ({
            ...site,
            domains: [...new Set(site.domains)].sort(),
        }))
        .sort((left, right) => left.domain.localeCompare(right.domain));
}
