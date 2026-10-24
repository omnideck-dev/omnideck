import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import TabStrip from '../TabStrip.jsx';

const TABS = [
    { id: 'one', label: 'One', icon: <i /> },
    { id: 'two', label: 'Two', icon: <i /> },
];

test('selects and closes tabs', () => {
    const onTabChange = vi.fn();
    const onCloseTab = vi.fn();
    render(
        <TabStrip
            tabs={TABS}
            activeTab="one"
            onTabChange={onTabChange}
            onCloseTab={onCloseTab}
        />,
    );

    fireEvent.click(screen.getByTestId('view-tab-two'));
    expect(onTabChange).toHaveBeenCalledWith('two');

    fireEvent.click(screen.getByTestId('close-view-tab-one'));
    expect(onCloseTab).toHaveBeenCalledWith('one');
    expect(onTabChange).toHaveBeenCalledTimes(1);
});

test('exposes tab semantics and supports arrow-key selection', () => {
    const onTabChange = vi.fn();
    render(
        <TabStrip
            tabs={TABS}
            activeTab="one"
            onTabChange={onTabChange}
            onCloseTab={vi.fn()}
        />,
    );

    const tabs = screen.getAllByRole('tab');
    expect(screen.getByRole('tablist', { name: 'Open views' }))
        .toContainElement(tabs[0]);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[1]).toHaveAttribute('tabindex', '-1');

    fireEvent.keyDown(tabs[0], { key: 'ArrowRight' });
    expect(onTabChange).toHaveBeenCalledWith('two');
    expect(tabs[1]).toHaveFocus();
});

test('shows controls for an overflowing tab strip and scrolls in both directions', () => {
    render(
        <TabStrip
            tabs={TABS}
            activeTab="one"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        />,
    );
    const tabList = screen.getByTestId('view-tab-one').parentElement.parentElement;
    Object.defineProperties(tabList, {
        clientWidth: { configurable: true, value: 200 },
        scrollWidth: { configurable: true, value: 600 },
        scrollLeft: { configurable: true, value: 0, writable: true },
        scrollTo: { configurable: true, value: vi.fn() },
    });
    fireEvent.resize(window);

    const scrollLeft = screen.getByRole('button', { name: 'Scroll tabs left' });
    const scrollRight = screen.getByRole('button', { name: 'Scroll tabs right' });
    expect(scrollLeft).toBeDisabled();
    expect(scrollRight).toBeEnabled();

    fireEvent.click(scrollRight);
    expect(tabList.scrollTo).toHaveBeenCalledWith({
        left: 160,
        behavior: 'smooth',
    });

    tabList.scrollLeft = 400;
    fireEvent.scroll(tabList);
    expect(scrollLeft).toBeEnabled();
    expect(scrollRight).toBeDisabled();
});

test('keeps the selected tab visible when the strip is already scrolled', () => {
    const props = {
        tabs: TABS,
        onTabChange: vi.fn(),
        onCloseTab: vi.fn(),
    };
    const { rerender } = render(<TabStrip {...props} activeTab="one" />);
    const tabList = screen.getByTestId('view-tab-one').parentElement.parentElement;
    const secondTab = screen.getByTestId('view-tab-two').parentElement;
    Object.defineProperties(tabList, {
        clientWidth: { configurable: true, value: 200 },
        scrollWidth: { configurable: true, value: 600 },
        scrollLeft: { configurable: true, value: 300, writable: true },
        getBoundingClientRect: {
            configurable: true,
            value: () => ({
                left: 600,
                right: 800,
            }),
        },
    });
    Object.defineProperty(secondTab, 'getBoundingClientRect', {
        configurable: true,
        value: () => ({
            left: 750,
            right: 900,
        }),
    });

    rerender(<TabStrip {...props} activeTab="two" />);

    expect(tabList.scrollLeft).toBe(400);
});

test('opens an inactive tab context menu without selecting the tab', () => {
    const execute = vi.fn();
    const onTabChange = vi.fn();
    render(
        <TabStrip
            tabs={TABS.map((tab) => ({
                ...tab,
                menuActions: [{
                    id: 'move',
                    label: 'Move to left tab group',
                    icon: 'bi-box-arrow-left',
                    execute,
                    disabled: false,
                }],
            }))}
            activeTab="one"
            onTabChange={onTabChange}
            onCloseTab={vi.fn()}
        />,
    );

    fireEvent.contextMenu(screen.getByTestId('view-tab-two'), {
        clientX: 100,
        clientY: 40,
    });

    expect(screen.getByRole('menu', { name: 'Tab actions' })).toBeInTheDocument();
    expect(onTabChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole(
        'menuitem',
        { name: 'Move to left tab group' },
    ));
    expect(execute).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu', { name: 'Tab actions' })).not.toBeInTheDocument();
});

test('opens the active tab action menu from one compact overflow button', () => {
    const execute = vi.fn();
    render(
        <TabStrip
            tabs={[{
                ...TABS[0],
                menuActions: [{
                    id: 'reload',
                    label: 'Reload',
                    icon: 'bi-arrow-clockwise',
                    execute,
                    disabled: false,
                    testid: 'reload-view-one',
                }],
            }]}
            activeTab="one"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        />,
    );

    fireEvent.click(screen.getByRole(
        'button',
        { name: 'Actions for One tab' },
    ));
    fireEvent.click(screen.getByTestId('reload-view-one'));

    expect(execute).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu', { name: 'Tab actions' }))
        .not.toBeInTheDocument();
});

test('active tab with menu actions shows both the menu and close buttons inline', () => {
    render(
        <TabStrip
            tabs={TABS.map((tab) => ({
                ...tab,
                menuActions: [{
                    id: 'reload',
                    label: 'Reload',
                    icon: 'bi-arrow-clockwise',
                    execute: vi.fn(),
                    disabled: false,
                }],
            }))}
            activeTab="one"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        />,
    );

    expect(screen.getByRole('button', { name: 'Actions for One tab' }))
        .toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close One tab' }))
        .toBeInTheDocument();
});

test('inactive tab with menu actions renders both buttons for hover reveal, closes without activating', () => {
    const onTabChange = vi.fn();
    const onCloseTab = vi.fn();
    render(
        <TabStrip
            tabs={TABS.map((tab) => ({
                ...tab,
                menuActions: [{
                    id: 'reload',
                    label: 'Reload',
                    icon: 'bi-arrow-clockwise',
                    execute: vi.fn(),
                    disabled: false,
                }],
            }))}
            activeTab="one"
            onTabChange={onTabChange}
            onCloseTab={onCloseTab}
        />,
    );

    // Inactive tab ("two") still exposes both controls in the DOM so a CSS
    // hover/focus-within reveal can show them without a re-render on mouse
    // enter.
    expect(screen.getByRole('button', { name: 'Actions for Two tab' }))
        .toBeInTheDocument();
    const closeTwo = screen.getByRole('button', { name: 'Close Two tab' });
    expect(closeTwo).toBeInTheDocument();

    fireEvent.click(closeTwo);
    expect(onCloseTab).toHaveBeenCalledWith('two');
    expect(onTabChange).not.toHaveBeenCalled();
});

test('menu and close buttons follow the active tab in the roving tabindex', () => {
    const props = {
        tabs: TABS.map((tab) => ({
            ...tab,
            menuActions: [{
                id: 'reload',
                label: 'Reload',
                icon: 'bi-arrow-clockwise',
                execute: vi.fn(),
                disabled: false,
            }],
        })),
        onTabChange: vi.fn(),
        onCloseTab: vi.fn(),
    };
    const { rerender } = render(<TabStrip {...props} activeTab="one" />);

    const actionsOne = () => screen.getByRole('button', { name: 'Actions for One tab' });
    const closeOne = () => screen.getByRole('button', { name: 'Close One tab' });
    const actionsTwo = () => screen.getByRole('button', { name: 'Actions for Two tab' });
    const closeTwo = () => screen.getByRole('button', { name: 'Close Two tab' });

    expect(actionsOne()).toHaveAttribute('tabindex', '0');
    expect(closeOne()).toHaveAttribute('tabindex', '0');
    expect(actionsTwo()).toHaveAttribute('tabindex', '-1');
    expect(closeTwo()).toHaveAttribute('tabindex', '-1');

    rerender(<TabStrip {...props} activeTab="two" />);

    expect(actionsOne()).toHaveAttribute('tabindex', '-1');
    expect(closeOne()).toHaveAttribute('tabindex', '-1');
    expect(actionsTwo()).toHaveAttribute('tabindex', '0');
    expect(closeTwo()).toHaveAttribute('tabindex', '0');
});

test('an inactive tab stays flagged as open while its own menu is open', () => {
    render(
        <TabStrip
            tabs={TABS.map((tab) => ({
                ...tab,
                menuActions: [{
                    id: 'reload',
                    label: 'Reload',
                    icon: 'bi-arrow-clockwise',
                    execute: vi.fn(),
                    disabled: false,
                }],
            }))}
            activeTab="one"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        />,
    );

    // tabMenuOpen forces the CSS hover reveal to stay on even once the
    // pointer leaves the tab for the popup, so the "⋯" trigger doesn't
    // disappear while aria-expanded is still true on it.
    const tabTwo = screen.getByTestId('view-tab-two').parentElement;
    expect(tabTwo.className).not.toMatch(/tabMenuOpen/);

    fireEvent.click(screen.getByRole('button', { name: 'Actions for Two tab' }));

    expect(tabTwo.className).toMatch(/tabMenuOpen/);
});

test('closes the tab action menu when its trigger is clicked again', () => {
    render(
        <TabStrip
            tabs={[{
                ...TABS[0],
                menuActions: [{
                    id: 'reload',
                    label: 'Reload',
                    icon: 'bi-arrow-clockwise',
                    execute: vi.fn(),
                    disabled: false,
                }],
            }]}
            activeTab="one"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        />,
    );

    // mousedown-then-click, not just click, because the real bug only shows
    // up through that sequence: the menu's outside-click listener closes on
    // mousedown, so a plain click re-fires open right after unless the
    // trigger's own mousedown is kept from reaching that listener.
    const trigger = screen.getByRole('button', { name: 'Actions for One tab' });
    fireEvent.mouseDown(trigger);
    fireEvent.click(trigger);
    expect(screen.getByRole('menu', { name: 'Tab actions' })).toBeInTheDocument();

    fireEvent.mouseDown(trigger);
    fireEvent.click(trigger);
    expect(screen.queryByRole('menu', { name: 'Tab actions' })).not.toBeInTheDocument();
});

test('opens the tab context menu from the keyboard', () => {
    render(
        <TabStrip
            tabs={[{
                ...TABS[0],
                menuActions: [{
                    id: 'close',
                    label: 'Close tab',
                    icon: 'bi-x-lg',
                    execute: vi.fn(),
                    disabled: false,
                }],
            }]}
            activeTab="one"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        />,
    );

    fireEvent.keyDown(screen.getByTestId('view-tab-one'), {
        key: 'F10',
        shiftKey: true,
    });

    expect(screen.getByRole('menuitem', { name: 'Close tab' })).toHaveFocus();
});

test('reopening the keyboard context menu on an already-open tab keeps it open', () => {
    render(
        <TabStrip
            tabs={[{
                ...TABS[0],
                menuActions: [{
                    id: 'close',
                    label: 'Close tab',
                    icon: 'bi-x-lg',
                    execute: vi.fn(),
                    disabled: false,
                }],
            }]}
            activeTab="one"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        />,
    );

    const tab = screen.getByTestId('view-tab-one');
    fireEvent.keyDown(tab, { key: 'F10', shiftKey: true });
    expect(screen.getByRole('menu', { name: 'Tab actions' })).toBeInTheDocument();

    // Unlike the "..." trigger button, the keyboard path has no toggle: a
    // second invocation re-opens/repositions rather than closing, since
    // there's no pointer feedback to explain a surprise close.
    fireEvent.keyDown(tab, { key: 'F10', shiftKey: true });
    expect(screen.getByRole('menu', { name: 'Tab actions' })).toBeInTheDocument();
});
