import { describe, expect, it } from 'vitest';

import {
    persistedDesktopView,
    validDesktopView,
} from '../desktopViews.js';

describe('generic Desktop View contract', () => {
    it('persists opaque domain identity without runtime fields', () => {
        const identity = {
            domainKey: 'resource-1',
            nested: { producer: 'agent-2' },
        };
        const runtimeView = {
            id: 'example:resource-1',
            type: 'example',
            label: 'Example',
            icon: 'bi-example',
            closable: true,
            identity,
            domainRecord: { large: true },
            actions: [{
                id: 'refresh',
                label: 'Refresh',
                icon: 'bi-arrow-clockwise',
            }],
            testMetadata: { ownerId: 'agent-2' },
        };

        expect(persistedDesktopView(runtimeView)).toEqual({
            id: 'example:resource-1',
            type: 'example',
            label: 'Example',
            icon: 'bi-example',
            closable: true,
            identity,
        });
    });

    it('requires an opaque identity record but not a registered domain type', () => {
        expect(validDesktopView({
            id: 'future:1',
            type: 'future-domain',
            label: 'Future',
            identity: {},
        })).toBe(true);
        expect(validDesktopView({
            id: 'future:1',
            type: 'future-domain',
            label: 'Future',
        })).toBe(false);
    });
});
