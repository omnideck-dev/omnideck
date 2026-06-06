import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import ChatPanel from '../ChatPanel.jsx';

// Use the real ChatInput here (the sibling ChatPanel suite stubs it) so we can
// exercise the draft-clearing behavior. The message list is irrelevant.
vi.mock('../ChatMessages.jsx', () => ({ default: () => <div data-testid="chat-messages" /> }));

function renderPanel(props = {}) {
    return render(
        <ChatPanel
            messages={[]}
            onSend={vi.fn()}
            onStop={vi.fn()}
            isStreaming={false}
            {...props}
        />,
    );
}

describe('ChatPanel draft handling', () => {
    beforeEach(() => {
        // ProfileSelector fetches profiles on mount; an empty list renders nothing.
        globalThis.fetch = vi.fn(() => Promise.resolve({ json: () => Promise.resolve([]) }));
    });

    it('discards unsent text when the active conversation changes', async () => {
        const user = userEvent.setup();
        const { rerender } = renderPanel({ conversationId: 'conv-a' });

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'half-written thought');
        expect(textarea.value).toBe('half-written thought');

        rerender(
            <ChatPanel messages={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false}
                conversationId="conv-b" />,
        );

        expect(screen.getByPlaceholderText('Message Omnideck…').value).toBe('');
    });

    it('keeps the text while the conversation stays the same', async () => {
        const user = userEvent.setup();
        const { rerender } = renderPanel({ conversationId: 'conv-a' });

        await user.type(screen.getByPlaceholderText('Message Omnideck…'), 'still typing');

        // Re-render with the same conversation but other props changing.
        rerender(
            <ChatPanel messages={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false}
                conversationId="conv-a" rootAgent={{ name: 'Omnideck' }} />,
        );

        expect(screen.getByPlaceholderText('Message Omnideck…').value).toBe('still typing');
    });
});
