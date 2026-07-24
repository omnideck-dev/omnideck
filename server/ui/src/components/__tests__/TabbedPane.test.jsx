import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import TabbedPane from '../TabbedPane.jsx';

const TABS = [
    { id: 'one', label: 'One', icon: <i /> },
    { id: 'two', label: 'Two', icon: <i /> },
];

test('renders tabs, actions, and caller-provided content', () => {
    const onTabChange = vi.fn();
    const onCloseTab = vi.fn();
    render(
        <TabbedPane
            tabs={TABS}
            activeTab="one"
            onTabChange={onTabChange}
            onCloseTab={onCloseTab}
            actions={<button>Reload</button>}
        >
            <div data-testid="selected-content" />
        </TabbedPane>,
    );

    fireEvent.click(screen.getByTestId('preview-tab-two'));
    expect(onTabChange).toHaveBeenCalledWith('two');

    fireEvent.click(screen.getByTestId('close-tab-one'));
    expect(onCloseTab).toHaveBeenCalledWith('one');
    expect(onTabChange).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
    expect(screen.getByTestId('selected-content')).toBeInTheDocument();
});

test('can hide its tab strip without remounting its content', () => {
    const props = {
        tabs: TABS,
        activeTab: 'one',
        onTabChange: vi.fn(),
        onCloseTab: vi.fn(),
    };
    const content = <div data-testid="selected-content" />;
    const { rerender } = render(
        <TabbedPane {...props}>{content}</TabbedPane>,
    );
    const selectedContent = screen.getByTestId('selected-content');

    rerender(<TabbedPane {...props} hideTabs>{content}</TabbedPane>);
    expect(screen.queryByTestId('preview-tab-bar')).not.toBeInTheDocument();
    expect(screen.getByTestId('selected-content')).toBe(selectedContent);
});
