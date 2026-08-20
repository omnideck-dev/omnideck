import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import QueuedNudges from '../QueuedNudges.jsx';

const NUDGES = [
    { id: 'nudge-1', agent_id: 'root-1', message: 'Keep the API compatible.' },
    { id: 'nudge-2', agent_id: 'root-1', message: 'Add deletion tests.' },
];

describe('QueuedNudges', () => {
    it('shows pending nudges in order and collapses to a live count', async () => {
        const user = userEvent.setup();
        render(<QueuedNudges nudges={NUDGES} onDelete={vi.fn()} />);

        const disclosure = screen.getByRole('button', { name: /Queued nudges 2/i });
        expect(disclosure).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByText('NEXT')).toBeInTheDocument();
        expect(screen.getByText('Keep the API compatible.')).toBeInTheDocument();
        expect(screen.getByText('Add deletion tests.')).toBeInTheDocument();

        await user.click(disclosure);

        expect(disclosure).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByText('Keep the API compatible.')).not.toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('deletes one addressable pending nudge', async () => {
        const user = userEvent.setup();
        const onDelete = vi.fn().mockResolvedValue({ ok: true });
        render(<QueuedNudges nudges={NUDGES} onDelete={onDelete} />);

        await user.click(screen.getByRole('button', {
            name: 'Delete queued nudge: Add deletion tests.',
        }));

        expect(onDelete).toHaveBeenCalledOnce();
        expect(onDelete).toHaveBeenCalledWith(NUDGES[1]);
    });
});
