import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import CustomAppLayout from '../CustomAppLayout.jsx';

function content() {
    return <div data-testid="custom-app-content" />;
}

test('changes from full-space to split layout without remounting its content', () => {
    const props = {
        visible: true,
        toolbar: <div data-testid="custom-app-toolbar" />,
        banner: <div data-testid="custom-app-banner" />,
    };
    const { rerender } = render(
        <CustomAppLayout {...props} layout="full">{content()}</CustomAppLayout>,
    );
    const appContent = screen.getByTestId('custom-app-content');
    expect(screen.getByTestId('custom-app-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('custom-app-banner')).toBeInTheDocument();

    rerender(<CustomAppLayout {...props} layout="split">{content()}</CustomAppLayout>);
    expect(screen.getByTestId('custom-app-content')).toBe(appContent);
    expect(screen.queryByTestId('custom-app-toolbar')).not.toBeInTheDocument();
    expect(screen.getByTestId('custom-app-layout')).toHaveAttribute('data-layout', 'split');
});

test('stays mounted while another shell view hides it', () => {
    const { rerender } = render(
        <CustomAppLayout visible layout="split">{content()}</CustomAppLayout>,
    );
    const appContent = screen.getByTestId('custom-app-content');

    rerender(
        <CustomAppLayout visible={false} layout="split">{content()}</CustomAppLayout>,
    );
    expect(screen.getByTestId('custom-app-layout')).toHaveAttribute('data-visible', 'false');
    expect(screen.getByTestId('custom-app-content')).toBe(appContent);
});
