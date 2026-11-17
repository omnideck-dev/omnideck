import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import ExpandableSelectionRow from '../ExpandableSelectionRow.jsx';

describe('ExpandableSelectionRow', () => {
    it('discloses details by mouse and keyboard with a stable accessible relationship', async () => {
        const user = userEvent.setup();
        render(<ul><ExpandableSelectionRow icon={<i />} name="Memory" description="Remember useful facts" onRemove={vi.fn()}>
            <button type="button">Detail action</button>
        </ExpandableSelectionRow></ul>);
        const toggle = screen.getByRole('button', { name: 'Memory', exact: true });
        expect(toggle).toHaveAccessibleDescription('Remember useful facts');
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByRole('button', { name: 'Detail action' })).not.toBeInTheDocument();
        await user.click(toggle);
        expect(toggle).toHaveAttribute('aria-expanded', 'true');
        expect(document.getElementById(toggle.getAttribute('aria-controls'))).toContainElement(screen.getByRole('button', { name: 'Detail action' }));
        await user.keyboard(' ');
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await user.keyboard('{Enter}');
        expect(toggle).toHaveAttribute('aria-expanded', 'true');
    });

    it('keeps removal outside the toggle and never expands when removing', async () => {
        const user = userEvent.setup(), onRemove = vi.fn();
        render(<ul><ExpandableSelectionRow icon={<i />} name="Work Google" description="Work account" onRemove={onRemove}>
            Details
        </ExpandableSelectionRow></ul>);
        const toggle = screen.getByRole('button', { name: 'Work Google', exact: true });
        const remove = screen.getByRole('button', { name: 'Remove Work Google' });
        expect(toggle).not.toContainElement(remove);
        await user.tab();
        expect(toggle).toHaveFocus();
        await user.tab();
        expect(remove).toHaveFocus();
        await user.keyboard('{Enter}');
        expect(onRemove).toHaveBeenCalledTimes(1);
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
    });

    it('keeps multiple rows independently expandable with unique content IDs', async () => {
        const user = userEvent.setup();
        render(<ul>{['Research', 'Memory'].map(name => <ExpandableSelectionRow key={name} icon={<i />} name={name} onRemove={vi.fn()}>{name} details</ExpandableSelectionRow>)}</ul>);
        const research = screen.getByRole('button', { name: 'Research', exact: true });
        const memory = screen.getByRole('button', { name: 'Memory', exact: true });
        expect(research.getAttribute('aria-controls')).not.toBe(memory.getAttribute('aria-controls'));
        await user.click(research);
        expect(research).toHaveAttribute('aria-expanded', 'true');
        expect(memory).toHaveAttribute('aria-expanded', 'false');
    });
});
