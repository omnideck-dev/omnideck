import { useEffect } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import ChatInput from '../ChatInput.jsx';

vi.mock('../../contexts/AppData.jsx', () => ({
    useAppData: () => ({
        skillsHook: {
            skills: [{ id: 'skill_review', name: 'review-code', description: '' }],
            loading: false,
            refresh: vi.fn(),
        },
    }),
}));

// The selected profile can't load skills.
vi.mock('../ProfileSelector.jsx', () => ({
    default: function ProfileSelector({ onSelectedProfile }) {
        useEffect(() => {
            onSelectedProfile({ id: 'locked', name: 'Locked', allow_load_skills: false });
        }, [onSelectedProfile]);
        return null;
    },
}));

describe('ChatInput with a profile that cannot load skills', () => {
    it('opens no list and shows no chip, only the plain-text hint', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Locked…');
        await user.type(textarea, '/rev');
        expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

        await user.type(textarea, 'iew-code');
        expect(screen.queryByTestId('composer-shortcuts')).not.toBeInTheDocument();
        expect(screen.getByText(/Locked can't load skills/)).toBeInTheDocument();

        await user.keyboard('{Enter}');
        expect(onSend).toHaveBeenCalledWith('/review-code', null);
    });
});
