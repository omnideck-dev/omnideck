import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import HomeAppUnavailable from '../HomeAppUnavailable.jsx';

test('offers shell-owned recovery for a missing Home app', () => {
    const onOpenApps = vi.fn();
    const onClearHome = vi.fn();
    render(
        <HomeAppUnavailable
            message="No matching Custom App was found."
            onOpenApps={onOpenApps}
            onClearHome={onClearHome}
        />,
    );

    expect(screen.getByText('No matching Custom App was found.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Choose another app'));
    fireEvent.click(screen.getByText('Use Chat as Home'));
    expect(onOpenApps).toHaveBeenCalledOnce();
    expect(onClearHome).toHaveBeenCalledOnce();
});
