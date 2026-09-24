import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import AppsView from '../AppsView.jsx';

const SAMPLE = {
    slug: 'text-lab',
    title: 'Text Lab',
    description: 'Inspect and transform text.',
    icon: 'bi-fonts',
    has_actions: true,
};

test('lists discovered apps and asks the shell to open one on the left', () => {
    const onOpenApp = vi.fn();
    render(<AppsView apps={[SAMPLE]} onOpenApp={onOpenApp} />);
    expect(screen.getByText('Text Lab')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /^Apps/ })).toBeInTheDocument();
    expect(screen.queryByText('text-lab')).not.toBeInTheDocument();
    expect(screen.queryByText('Python')).not.toBeInTheDocument();
    expect(screen.getByTestId('custom-app-card').querySelector('.bi-chevron-right'))
        .not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('custom-app-card'));
    expect(onOpenApp).toHaveBeenCalledWith(SAMPLE);
});

test('asks the catalog owner to refresh', () => {
    const onRefresh = vi.fn();
    render(<AppsView apps={[SAMPLE]} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByTestId('custom-apps-refresh'));
    expect(onRefresh).toHaveBeenCalledOnce();
});

test('pins and unpins an App from its Hub card without opening it', () => {
    const onOpenApp = vi.fn();
    const onPinApp = vi.fn();
    const onUnpinApp = vi.fn();
    const { rerender } = render(
        <AppsView
            apps={[SAMPLE]}
            onOpenApp={onOpenApp}
            onPinApp={onPinApp}
            onUnpinApp={onUnpinApp}
        />,
    );

    fireEvent.click(screen.getByTestId('custom-app-pin-text-lab'));
    expect(onPinApp).toHaveBeenCalledWith('text-lab');
    expect(onOpenApp).not.toHaveBeenCalled();

    rerender(
        <AppsView
            apps={[SAMPLE]}
            pinnedAppSlugs={['text-lab']}
            onOpenApp={onOpenApp}
            onPinApp={onPinApp}
            onUnpinApp={onUnpinApp}
        />,
    );
    expect(screen.getByTestId('custom-app-pin-text-lab')).toHaveAttribute(
        'aria-pressed',
        'true',
    );
    fireEvent.click(screen.getByTestId('custom-app-pin-text-lab'));
    expect(onUnpinApp).toHaveBeenCalledWith('text-lab');
    expect(onOpenApp).not.toHaveBeenCalled();
});

test('keeps the empty state focused on Apps rather than implementation details', () => {
    render(<AppsView />);

    expect(screen.getByText('No Apps yet')).toBeInTheDocument();
    expect(screen.getByText('Ask your Omnideck agent to build one for you.')).toBeInTheDocument();
    expect(screen.queryByText(/folder|omnideck\.json|web\/index|~\/apps/i)).not.toBeInTheDocument();
});
