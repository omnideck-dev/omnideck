import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import BrandTabs from '../BrandTabs.jsx';

const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'tools', label: 'Tools', count: 3 },
    { id: 'connection', label: 'Connection' },
];

describe('BrandTabs', () => {
    it('renders counts and exposes the active tab', () => {
        render(
            <BrandTabs
                tabs={TABS}
                activeTab="tools"
                onTabChange={vi.fn()}
                ariaLabel="Integration settings"
                idBase="integration"
            />,
        );

        expect(screen.getByRole('tab', { name: 'Tools 3' })).toHaveAttribute('aria-selected', 'true');
        expect(screen.getByRole('tab', { name: 'Tools 3' })).toHaveAttribute(
            'aria-controls',
            'integration-panel-tools',
        );
        expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'false');
    });

    it('changes tabs with clicks and arrow keys', () => {
        const onTabChange = vi.fn();
        render(
            <BrandTabs
                tabs={TABS}
                activeTab="overview"
                onTabChange={onTabChange}
                ariaLabel="Integration settings"
            />,
        );

        fireEvent.click(screen.getByRole('tab', { name: 'Connection' }));
        expect(onTabChange).toHaveBeenLastCalledWith('connection');

        fireEvent.keyDown(screen.getByRole('tab', { name: 'Overview' }), { key: 'ArrowRight' });
        expect(onTabChange).toHaveBeenLastCalledWith('tools');
        expect(screen.getByRole('tab', { name: 'Tools 3' })).toHaveFocus();
    });
});
