import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import BrowserProfileMenu, { EMPTY_BROWSER_PROFILE } from '../BrowserProfileMenu.jsx';

const PROFILES = [
    { id: 'default', name: 'Default', icon: 'bi-globe2' },
    { id: 'linkedin', name: 'LinkedIn', icon: 'bi-linkedin' },
];

describe('BrowserProfileMenu', () => {
    it('selects Browser state from an accessible profile menu', async () => {
        const onChange = vi.fn();
        render(
            <BrowserProfileMenu
                profiles={PROFILES}
                value="linkedin"
                onChange={onChange}
            />,
        );

        const trigger = screen.getByTestId('browser-profile-select');
        expect(trigger).toHaveAccessibleName('Browser state: LinkedIn');
        expect(trigger).toHaveAttribute('data-value', 'linkedin');

        fireEvent.click(trigger);
        const selected = screen.getByRole('menuitemradio', { name: 'LinkedIn' });
        expect(selected).toHaveAttribute('aria-checked', 'true');
        await waitFor(() => expect(selected).toHaveFocus());

        fireEvent.click(screen.getByRole('menuitemradio', { name: 'Empty' }));
        expect(onChange).toHaveBeenCalledWith(EMPTY_BROWSER_PROFILE);
        expect(screen.queryByTestId('browser-profile-select-menu')).not.toBeInTheDocument();
    });

    it('keeps save visible and profile management in the menu', () => {
        const onSave = vi.fn();
        const onManage = vi.fn();
        render(
            <BrowserProfileMenu
                profiles={PROFILES}
                value="default"
                onSave={onSave}
                onManage={onManage}
            />,
        );

        fireEvent.click(screen.getByTestId('browser-save-state'));
        expect(onSave).toHaveBeenCalledOnce();

        fireEvent.click(screen.getByTestId('browser-profile-select'));
        fireEvent.click(screen.getByRole('menuitem', { name: 'Manage browser profiles' }));
        expect(onManage).toHaveBeenCalledOnce();
    });
});
