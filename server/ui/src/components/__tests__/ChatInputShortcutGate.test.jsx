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

// The selected profile can't load skills on its own.
vi.mock('../ProfileSelector.jsx', () => ({
    default: function ProfileSelector({ onSelectedProfile }) {
        useEffect(() => {
            onSelectedProfile({ id: 'locked', name: 'Locked', allow_load_skills: false });
        }, [onSelectedProfile]);
        return null;
    },
}));

describe('ChatInput with a profile that cannot load skills on its own', () => {
    it('still lets the user select a skill explicitly', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Locked…');
        await user.type(textarea, '/rev');
        await user.click(await screen.findByText('review-code'));
        expect(screen.getByTestId('composer-shortcuts')).toHaveTextContent('review-code');

        await user.keyboard('{Enter}');
        expect(onSend).toHaveBeenCalledWith('/review-code', null, [{ id: 'skill_review', name: 'review-code' }]);
    });
});
