import { describe, expect, it } from 'vitest';

import { groupBrowserSites, registrableDomain } from '../browserSites.js';

describe('browser site grouping', () => {
    it('uses the registrable domain instead of naively taking the last two labels', () => {
        expect(registrableDomain('accounts.example.co.uk')).toBe('example.co.uk');
        expect(registrableDomain('localhost')).toBe('localhost');
        expect(registrableDomain('127.0.0.1')).toBe('127.0.0.1');
    });

    it('combines subdomain summaries without losing their underlying domains', () => {
        expect(groupBrowserSites([
            { domain: 'about.linkedin.com', cookies: 0, local_storage: true, indexed_db: false },
            { domain: '.linkedin.com', cookies: 30, local_storage: false, indexed_db: false },
            { domain: 'news.linkedin.com', cookies: 0, local_storage: true, indexed_db: false },
            { domain: 'www.linkedin.com', cookies: 8, local_storage: true, indexed_db: true },
        ])).toEqual([{
            domain: 'linkedin.com',
            domains: [
                'about.linkedin.com',
                'linkedin.com',
                'news.linkedin.com',
                'www.linkedin.com',
            ],
            cookies: 38,
            local_storage: true,
            indexed_db: true,
        }]);
    });
});
