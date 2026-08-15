import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import Select from '../Select.jsx';

const options = [
    { value: 'omni', label: 'Omnideck' },
    { value: 'research', label: 'Research' },
    { value: 'disabled', label: 'Unavailable', disabled: true },
    { value: 'developer', label: 'Developer' },
];

describe('Select', () => {
    it('exposes its name, value, expanded state, and selected option', () => {
        render(
            <Select
                ariaLabel="Agent profile"
                options={options}
                value="omni"
                onChange={vi.fn()}
                testId="profile-select"
            />,
        );

        const trigger = screen.getByRole('combobox', { name: 'Agent profile' });
        expect(trigger).toHaveAttribute('data-value', 'omni');
        expect(trigger).toHaveAttribute('aria-expanded', 'false');

        fireEvent.click(trigger);
        expect(trigger).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByRole('option', { name: 'Omnideck' })).toHaveAttribute('aria-selected', 'true');
        expect(screen.getByTestId('profile-select-menu').parentElement).toBe(document.body);
    });

    it('selects with the mouse and returns focus to the trigger', () => {
        const onChange = vi.fn();
        render(<Select ariaLabel="Profile" options={options} value="omni" onChange={onChange} />);

        const trigger = screen.getByRole('combobox', { name: 'Profile' });
        fireEvent.click(trigger);
        fireEvent.click(screen.getByRole('option', { name: 'Research' }));

        expect(onChange).toHaveBeenCalledWith('research', options[1]);
        expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
        expect(trigger).toHaveFocus();
    });

    it('supports arrows, Home, End, Enter, Escape, and skips disabled options', async () => {
        const onChange = vi.fn();
        render(<Select ariaLabel="Profile" options={options} value="omni" onChange={onChange} />);
        const trigger = screen.getByRole('combobox', { name: 'Profile' });

        trigger.focus();
        fireEvent.keyDown(trigger, { key: 'ArrowDown' });
        expect(screen.getByRole('listbox')).toBeInTheDocument();

        fireEvent.keyDown(trigger, { key: 'ArrowDown' });
        expect(trigger).toHaveAttribute('aria-activedescendant', expect.stringContaining('option-1'));
        fireEvent.keyDown(trigger, { key: 'ArrowDown' });
        expect(trigger).toHaveAttribute('aria-activedescendant', expect.stringContaining('option-3'));
        fireEvent.keyDown(trigger, { key: 'Home' });
        expect(trigger).toHaveAttribute('aria-activedescendant', expect.stringContaining('option-0'));
        fireEvent.keyDown(trigger, { key: 'End' });
        fireEvent.keyDown(trigger, { key: 'Enter' });
        expect(onChange).toHaveBeenCalledWith('developer', options[3]);

        fireEvent.keyDown(trigger, { key: ' ' });
        fireEvent.keyDown(trigger, { key: 'Escape' });
        expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
        expect(trigger).toHaveFocus();
    });

    it('supports typeahead and emits no selection while disabled', () => {
        const onChange = vi.fn();
        const { rerender } = render(
            <Select ariaLabel="Profile" options={options} value="omni" onChange={onChange} />,
        );
        const trigger = screen.getByRole('combobox', { name: 'Profile' });
        trigger.focus();
        fireEvent.keyDown(trigger, { key: 'd' });
        expect(onChange).toHaveBeenCalledWith('developer', options[3]);

        onChange.mockClear();
        rerender(
            <Select ariaLabel="Profile" options={options} value="omni" onChange={onChange} disabled />,
        );
        expect(trigger).toBeDisabled();
        fireEvent.keyDown(trigger, { key: 'ArrowDown' });
        expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
        expect(onChange).not.toHaveBeenCalled();
    });

    it('keeps a controlled hidden form value without exposing a native select', () => {
        const { container } = render(
            <Select ariaLabel="Profile" name="profile" options={options} value="research" />,
        );
        expect(container.querySelector('select')).not.toBeInTheDocument();
        expect(container.querySelector('input[name="profile"]')).toHaveValue('research');
    });
});
