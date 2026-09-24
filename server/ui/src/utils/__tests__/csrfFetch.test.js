import { describe, expect, it, vi } from 'vitest';
import { csrfFetch } from '../csrfFetch.js';

describe('csrfFetch', () => {
    it('adds the CSRF header to mutating application requests', () => {
        const originalFetch = vi.fn();
        const wrapped = csrfFetch(originalFetch, 'http://127.0.0.1:2337/');

        wrapped('/api/settings', { method: 'PUT', headers: { Accept: 'application/json' } });

        const [, options] = originalFetch.mock.calls[0];
        expect(options.headers.get('Accept')).toBe('application/json');
        expect(options.headers.get('X-Requested-With')).toBe('XMLHttpRequest');
    });

    it('leaves Tauri IPC requests and their invoke key untouched', () => {
        const originalFetch = vi.fn();
        const wrapped = csrfFetch(originalFetch, 'http://127.0.0.1:2337/');
        const options = {
            method: 'POST',
            headers: new Headers({ 'Tauri-Invoke-Key': 'per-webview-secret' }),
        };

        wrapped('ipc://localhost/check_for_update', options);

        expect(originalFetch).toHaveBeenCalledWith(
            'ipc://localhost/check_for_update',
            options,
        );
        expect(options.headers.get('Tauri-Invoke-Key')).toBe('per-webview-secret');
        expect(options.headers.has('X-Requested-With')).toBe(false);
    });
});
