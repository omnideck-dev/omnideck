import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import ChatInput from '../ChatInput.jsx';

// Minimal 1x1 transparent PNG base64
const MOCK_BASE64_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAADElEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==';

const skillsHook = {
    skills: [
        { id: 'skill_review', name: 'review-code', description: 'Reviews a diff for bugs.' },
        { id: 'skill_sum', name: 'summarize', description: 'Summarizes a thread.' },
    ],
    loading: false,
    refresh: vi.fn(),
};

vi.mock('../../contexts/AppData.jsx', () => ({
    useAppData: () => ({ skillsHook }),
}));

describe('ChatInput', () => {
    it('renders textarea and buttons', () => {
        render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

        expect(screen.getByPlaceholderText('Message Omnideck…')).toBeInTheDocument();
        expect(screen.getByLabelText('Attach file')).toBeInTheDocument();
        expect(screen.getByLabelText('Send message')).toBeInTheDocument();
    });

    it('calls onSend with message when submitted', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'Hello world');
        await user.click(screen.getByLabelText('Send message'));

        expect(onSend).toHaveBeenCalledWith('Hello world', null, []);
    });

    it('trims whitespace from messages', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, '  test message  ');
        await user.click(screen.getByLabelText('Send message'));

        expect(onSend).toHaveBeenCalledWith('test message', null, []);
    });

    it('clears message after sending', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'Hello');
        await user.click(screen.getByLabelText('Send message'));

        expect(textarea.value).toBe('');
    });

    it('submits on Enter key press', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'Test{Enter}');

        expect(onSend).toHaveBeenCalledWith('Test', null, []);
    });

    it('does not submit on Shift+Enter', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'Line 1{Shift>}{Enter}{/Shift}Line 2');

        expect(onSend).not.toHaveBeenCalled();
        expect(textarea.value).toContain('Line 1\nLine 2');
    });

    it('shows stop button and nudge placeholder when streaming', () => {
        render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming={true} />);

        expect(screen.getByLabelText('Stop generation')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Send a nudge…')).toBeInTheDocument();
        // While streaming the send button is replaced by stop.
        expect(screen.queryByLabelText('Send message')).not.toBeInTheDocument();
    });

    it('keeps streaming controls visible but disables nudges after stop is requested', () => {
        render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming={true} stopRequested={true} />);

        // The button's label flips to 'Stopping' once requested; the
        // stable handle is its testid.
        expect(screen.getByTestId('chat-stop-btn')).toBeDisabled();
        expect(screen.getByPlaceholderText('Stopping…')).toBeDisabled();
        expect(screen.queryByLabelText('Send message')).not.toBeInTheDocument();
    });

    it('builds the placeholder from the selected profile name', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
            json: () => Promise.resolve([{ id: 'p1', name: 'Code Expert' }]),
        });
        try {
            render(<ChatInput onSend={vi.fn()} isStreaming={false}
                selectedProfileId="p1" onProfileChange={vi.fn()} />);
            expect(await screen.findByPlaceholderText('Message Code Expert…')).toBeInTheDocument();
        } finally {
            fetchSpy.mockRestore();
        }
    });

    it('names the profile in the streaming nudge placeholder', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
            json: () => Promise.resolve([{ id: 'p1', name: 'Code Expert' }]),
        });
        try {
            render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming={true}
                selectedProfileId="p1" onProfileChange={vi.fn()} />);
            expect(await screen.findByPlaceholderText('Send a nudge to Code Expert…')).toBeInTheDocument();
        } finally {
            fetchSpy.mockRestore();
        }
    });

    it('disables the send button when there is nothing to send', () => {
        render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
        expect(screen.getByLabelText('Send message')).toBeDisabled();
    });

    it('keeps the draft and blocks submission while offline', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(
            <ChatInput
                onSend={onSend}
                isStreaming={false}
                isOffline={true}
            />,
        );

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'send this later');
        await user.keyboard('{Enter}');

        expect(onSend).not.toHaveBeenCalled();
        expect(textarea).toHaveValue('send this later');
        expect(screen.getByLabelText('Send message')).toBeDisabled();
        expect(screen.getByTestId('connection-status')).toHaveTextContent(
            'OfflineMessages and controls are unavailable.',
        );
    });

    it('disables stop while offline', () => {
        render(
            <ChatInput
                onSend={vi.fn()}
                onStop={vi.fn()}
                isStreaming={true}
                isOffline={true}
            />,
        );

        expect(screen.getByTestId('chat-stop-btn')).toBeDisabled();
    });

    it('renders a file card (not an image) for a non-image attachment', async () => {
        render(<ChatInput onSend={vi.fn()} isStreaming={false}
            attachment={{ base64: 'YWJj', contentType: 'application/pdf', filename: 'report.pdf' }} />);
        expect(await screen.findByTitle('report.pdf')).toBeInTheDocument();
        expect(screen.getByText(/^PDF/)).toBeInTheDocument();
        expect(screen.queryByTestId('attachment-image')).not.toBeInTheDocument();
    });

    it('handles file selection and displays preview', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const file = new File(['dummy'], 'test.png', { type: 'image/png' });
        const fileInput = screen.getByLabelText('Attach file').closest('div').querySelector('input[type="file"]');

        await user.upload(fileInput, file);

        await waitFor(() => {
            expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
        });
    });

    it('removes file attachment when remove button clicked', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const file = new File(['dummy'], 'test.png', { type: 'image/png' });
        const fileInput = screen.getByLabelText('Attach file').closest('div').querySelector('input[type="file"]');

        await user.upload(fileInput, file);

        await waitFor(() => {
            expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
        });

        const removeButton = screen.getByLabelText('Remove attachment');
        await user.click(removeButton);

        expect(screen.queryByTestId('attachment-image')).not.toBeInTheDocument();
    });

    it('sends file data with message', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        // Create a mock file
        const fileContent = MOCK_BASE64_PNG;
        const file = new File([atob(fileContent)], 'test.png', { type: 'image/png' });
        const fileInput = screen.getByLabelText('Attach file').closest('div').querySelector('input[type="file"]');

        await user.upload(fileInput, file);

        await waitFor(() => {
            expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
        });

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'Check this image');
        await user.click(screen.getByLabelText('Send message'));

        expect(onSend).toHaveBeenCalledWith(
            'Check this image',
            expect.arrayContaining([
                expect.objectContaining({
                    content_type: 'image/png',
                    base64: expect.any(String),
                    filename: 'test.png',
                }),
            ]),
            [],
        );
    });

    it('clears file after sending', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const file = new File(['dummy'], 'test.png', { type: 'image/png' });
        const fileInput = screen.getByLabelText('Attach file').closest('div').querySelector('input[type="file"]');

        await user.upload(fileInput, file);

        await waitFor(() => {
            expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
        });

        await user.click(screen.getByLabelText('Send message'));

        expect(screen.queryByTestId('attachment-image')).not.toBeInTheDocument();
    });

    describe('draft persistence', () => {
        beforeEach(() => {
            localStorage.clear();
        });

        it('saves typed text to local storage under the conversation id', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} conversationId="convo-1" />);

            await user.type(screen.getByPlaceholderText('Message Omnideck…'), 'unsent draft');

            expect(localStorage.getItem('omnideck_chat_draft_v1:convo-1')).toBe('unsent draft');
        });

        it('restores a saved draft when remounted for the same conversation', () => {
            localStorage.setItem('omnideck_chat_draft_v1:convo-1', 'still here');

            render(<ChatInput onSend={vi.fn()} isStreaming={false} conversationId="convo-1" />);

            expect(screen.getByPlaceholderText('Message Omnideck…').value).toBe('still here');
        });

        it('does not leak a draft into a different conversation', () => {
            localStorage.setItem('omnideck_chat_draft_v1:convo-1', 'convo one text');

            render(<ChatInput onSend={vi.fn()} isStreaming={false} conversationId="convo-2" />);

            expect(screen.getByPlaceholderText('Message Omnideck…').value).toBe('');
        });

        it('clears the persisted draft once the message is sent', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} conversationId="convo-1" />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, 'Hello');
            await user.click(screen.getByLabelText('Send message'));

            expect(localStorage.getItem('omnideck_chat_draft_v1:convo-1')).toBeNull();
        });

        describe('with a throwing storage getter', () => {
            let descriptor;

            beforeEach(() => {
                descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
                Object.defineProperty(globalThis, 'localStorage', {
                    configurable: true,
                    get() {
                        throw new DOMException('Storage access blocked', 'SecurityError');
                    },
                });
            });

            afterEach(() => {
                Object.defineProperty(globalThis, 'localStorage', descriptor);
            });

            it('mounts and accepts input without throwing', async () => {
                const user = userEvent.setup();
                expect(() => render(
                    <ChatInput onSend={vi.fn()} isStreaming={false} conversationId="convo-1" />,
                )).not.toThrow();

                const textarea = screen.getByPlaceholderText('Message Omnideck…');
                expect(textarea.value).toBe('');
                await expect(user.type(textarea, 'still works')).resolves.not.toThrow();
                expect(textarea.value).toBe('still works');
            });
        });
    });

    describe('attachment prop', () => {
        it('sets attachment when attachment prop is provided', async () => {
            const onSend = vi.fn();
            const { rerender } = render(<ChatInput onSend={onSend} isStreaming={false} />);

            expect(screen.queryByTestId('attachment-image')).not.toBeInTheDocument();

            rerender(
                <ChatInput
                    onSend={onSend}
                    isStreaming={false}
                    attachment={{ base64: MOCK_BASE64_PNG, contentType: 'image/png' }}
                />
            );

            await waitFor(() => {
                expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
            });
        });

        it('sends attached file with message', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            render(
                <ChatInput
                    onSend={onSend}
                    isStreaming={false}
                    attachment={{ base64: MOCK_BASE64_PNG, contentType: 'image/png' }}
                />
            );

            await waitFor(() => {
                expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
            });

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, 'External image');
            await user.click(screen.getByLabelText('Send message'));

            expect(onSend).toHaveBeenCalledWith(
                'External image',
                expect.arrayContaining([
                    expect.objectContaining({
                        content_type: 'image/png',
                        base64: MOCK_BASE64_PNG,
                    }),
                ]),
                [],
            );
        });

        it('uses default contentType when not provided', async () => {
            const onSend = vi.fn();
            render(
                <ChatInput
                    onSend={onSend}
                    isStreaming={false}
                    attachment={{ base64: MOCK_BASE64_PNG }}
                />
            );

            await waitFor(() => {
                expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
            });
        });

        it('can remove attached file', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            render(
                <ChatInput
                    onSend={onSend}
                    isStreaming={false}
                    attachment={{ base64: MOCK_BASE64_PNG, contentType: 'image/png' }}
                />
            );

            await waitFor(() => {
                expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
            });

            const removeButton = screen.getByLabelText('Remove attachment');
            await user.click(removeButton);

            expect(screen.queryByTestId('attachment-image')).not.toBeInTheDocument();
        });
    });

    describe('composer / trigger', () => {
        it('opens the skill list on / and inserts the token on selection', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/rev');

            expect(await screen.findByRole('listbox', { name: 'Skills' })).toBeInTheDocument();
            expect(screen.getByText('review-code')).toBeInTheDocument();
            expect(screen.queryByText('summarize')).not.toBeInTheDocument();

            await user.click(screen.getByText('review-code'));

            expect(textarea.value).toBe('/review-code ');
            expect(screen.queryByRole('listbox', { name: 'Skills' })).not.toBeInTheDocument();
        });

        it('closes the overlay once the filtered list is empty', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/zzz');

            expect(screen.queryByRole('listbox', { name: 'Skills' })).not.toBeInTheDocument();
        });

        it('does not open an overlay on @', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '@');

            expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
        });

        it('does not open the overlay for a mid-word slash', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, 'a/b');

            expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
        });

        it('commits the highlighted skill on Enter once something is typed', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            render(<ChatInput onSend={onSend} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/r');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{Enter}');

            expect(onSend).not.toHaveBeenCalled();
            expect(textarea.value).toBe('/review-code ');
        });

        it('sends on Enter when the typed token already names the highlighted skill', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            render(<ChatInput onSend={onSend} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, 'summarize this /review-code');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{Enter}');

            expect(onSend).toHaveBeenCalledWith(
                'summarize this /review-code',
                null,
                [{ type: 'skill', skill_id: 'skill_review', name: 'review-code' }],
            );
        });

        it('sends on Enter after a bare trigger the user has not moved into', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            render(<ChatInput onSend={onSend} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, 'a or /');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{Enter}');

            expect(onSend).toHaveBeenCalledWith('a or /', null, []);
        });

        it('commits from a bare trigger with Tab or after arrowing into the list', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{Tab}');
            expect(textarea.value).toBe('/review-code ');

            await user.type(textarea, '/');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{ArrowDown}{Enter}');
            expect(textarea.value).toBe('/review-code /summarize ');
        });

        it('finds a multi-word skill by typing its slug', async () => {
            const user = userEvent.setup();
            skillsHook.skills = [{ id: '4dffecbf8559', name: 'Joke teller', description: '' }];
            try {
                render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
                await user.type(screen.getByPlaceholderText('Message Omnideck…'), '/joke-t');

                expect(await screen.findByText('Joke teller')).toBeInTheDocument();
            } finally {
                skillsHook.skills = [
                    { id: 'skill_review', name: 'review-code', description: 'Reviews a diff for bugs.' },
                    { id: 'skill_sum', name: 'summarize', description: 'Summarizes a thread.' },
                ];
            }
        });

        it('keeps the highlighted row when a refresh replaces the skills', async () => {
            const user = userEvent.setup();
            const { rerender } = render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            await user.type(screen.getByPlaceholderText('Message Omnideck…'), '/');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{ArrowDown}');

            const original = skillsHook.skills;
            skillsHook.skills = [...original];
            try {
                rerender(<ChatInput onSend={vi.fn()} isStreaming={false} />);
                expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
            } finally {
                skillsHook.skills = original;
            }
        });

        it('closes the list when a run starts', async () => {
            const user = userEvent.setup();
            const { rerender } = render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            await user.type(screen.getByPlaceholderText('Message Omnideck…'), '/');
            await screen.findByRole('listbox', { name: 'Skills' });
            rerender(<ChatInput onSend={vi.fn()} isStreaming />);

            expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
        });

        it('keeps the arrow-key selection after the keyup that follows it', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/');
            await screen.findByRole('listbox', { name: 'Skills' });

            await user.keyboard('{ArrowDown}');

            const options = screen.getAllByRole('option');
            expect(options[1]).toHaveAttribute('aria-selected', 'true');
            expect(options[0]).toHaveAttribute('aria-selected', 'false');
        });

        it('does not crash committing Enter when the list narrows before the stale index resets', () => {
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
            const textarea = screen.getByPlaceholderText('Message Omnideck…');

            fireEvent.change(textarea, { target: { value: '/' } });
            fireEvent.keyDown(textarea, { key: 'ArrowDown' });
            fireEvent.keyUp(textarea, { key: 'ArrowDown' });

            // Both fire inside one act() so React doesn't get a chance to
            // flush the reset-to-0 effect between them — the same race a
            // real narrowing keystroke immediately followed by Enter could
            // hit with no event-loop turn in between.
            expect(() => {
                act(() => {
                    fireEvent.change(textarea, { target: { value: '/summ' } });
                    fireEvent.keyDown(textarea, { key: 'Enter' });
                });
            }).not.toThrow();

            expect(textarea.value).toBe('/summarize ');
        });

        it('closes the overlay on Escape without collapsing the composer', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{Escape}');

            expect(screen.queryByRole('listbox', { name: 'Skills' })).not.toBeInTheDocument();
            expect(textarea.value).toBe('/');
        });

        it('sends on Enter before the skill list has loaded', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            skillsHook.loading = true;
            skillsHook.skills = [];
            try {
                render(<ChatInput onSend={onSend} isStreaming={false} />);
                const textarea = screen.getByPlaceholderText('Message Omnideck…');
                await user.type(textarea, 'what is in /etc/hosts{Enter}');

                expect(onSend).toHaveBeenCalledWith('what is in /etc/hosts', null, []);
            } finally {
                skillsHook.loading = false;
                skillsHook.skills = [
                    { id: 'skill_review', name: 'review-code', description: 'Reviews a diff for bugs.' },
                    { id: 'skill_sum', name: 'summarize', description: 'Summarizes a thread.' },
                ];
            }
        });

        it('adds a new line on Shift+Enter while the list is open', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/rev');
            await screen.findByRole('listbox', { name: 'Skills' });
            await user.keyboard('{Shift>}{Enter}{/Shift}');

            expect(textarea.value).toBe('/rev\n');
        });

        it('leaves an IME-confirming Enter to the input method', () => {
            const onSend = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} />);
            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            fireEvent.change(textarea, { target: { value: '/rev' } });
            fireEvent.keyUp(textarea, { key: 'v' });

            fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true });

            expect(textarea.value).toBe('/rev');
            expect(onSend).not.toHaveBeenCalled();
        });

        it('inserts a slug for a multi-word skill name instead of the raw id', async () => {
            const user = userEvent.setup();
            skillsHook.skills = [
                { id: '4dffecbf8559', name: 'Joke teller', description: 'Tells a joke.' },
            ];
            try {
                render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
                const textarea = screen.getByPlaceholderText('Message Omnideck…');
                await user.type(textarea, '/Joke');
                await user.click(await screen.findByText('Joke teller'));

                expect(textarea.value).toBe('/joke-teller ');
            } finally {
                skillsHook.skills = [
                    { id: 'skill_review', name: 'review-code', description: 'Reviews a diff for bugs.' },
                    { id: 'skill_sum', name: 'summarize', description: 'Summarizes a thread.' },
                ];
            }
        });

        it('falls back to the raw id when two multi-word skill names collide on the same slug', async () => {
            const user = userEvent.setup();
            skillsHook.skills = [
                { id: '4dffecbf8559', name: 'Joke teller', description: 'Tells a joke.' },
                { id: 'aaaaaaaaaaaa', name: 'joke   TELLER!!', description: 'Also tells a joke.' },
            ];
            try {
                render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
                const textarea = screen.getByPlaceholderText('Message Omnideck…');
                await user.type(textarea, '/Joke');
                await user.click(await screen.findByText('Joke teller'));

                expect(textarea.value).toBe('/4dffecbf8559 ');
            } finally {
                skillsHook.skills = [
                    { id: 'skill_review', name: 'review-code', description: 'Reviews a diff for bugs.' },
                    { id: 'skill_sum', name: 'summarize', description: 'Summarizes a thread.' },
                ];
            }
        });

        it('does not open the overlay while the agent is running', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming />);

            const textarea = screen.getByPlaceholderText('Send a nudge…');
            await user.type(textarea, '/rev');

            expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
        });

        it('sends a path on Enter during a background refresh of cached skills', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            skillsHook.loading = true;
            try {
                render(<ChatInput onSend={onSend} isStreaming={false} />);
                const textarea = screen.getByPlaceholderText('Message Omnideck…');
                await user.type(textarea, 'check /var/log{Enter}');

                expect(onSend).toHaveBeenCalledWith('check /var/log', null, []);
            } finally {
                skillsHook.loading = false;
            }
        });

        it('shows a chip for a selected skill', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/rev');
            await user.click(await screen.findByText('review-code'));

            const tray = screen.getByTestId('composer-shortcuts');
            expect(tray).toHaveTextContent('Skillreview-code');
        });

        it('shows no chip for text that names no skill', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            await user.type(screen.getByPlaceholderText('Message Omnideck…'), 'check /etc/hosts ');

            expect(screen.queryByTestId('composer-shortcuts')).not.toBeInTheDocument();
        });

        it('removes the token from the message when its chip is removed', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            fireEvent.change(textarea, { target: { value: '/summarize this thread' } });
            await user.click(screen.getByRole('button', { name: 'Remove skill summarize' }));

            expect(textarea.value).toBe('this thread');
            expect(screen.queryByTestId('composer-shortcuts')).not.toBeInTheDocument();
        });

        it('shows one chip per skill even when its token repeats', () => {
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
            fireEvent.change(screen.getByPlaceholderText('Message Omnideck…'), {
                target: { value: '/summarize a then /summarize b' },
            });

            expect(screen.getAllByRole('button', { name: 'Remove skill summarize' })).toHaveLength(1);
        });

        it('sends the chips as typed context items with the message', async () => {
            const onSend = vi.fn();
            const user = userEvent.setup();
            render(<ChatInput onSend={onSend} isStreaming={false} />);

            const textarea = screen.getByPlaceholderText('Message Omnideck…');
            await user.type(textarea, '/rev');
            await user.click(await screen.findByText('review-code'));
            await user.type(textarea, 'check /etc/hosts{Enter}');

            expect(onSend).toHaveBeenCalledWith(
                '/review-code check /etc/hosts',
                null,
                [{ type: 'skill', skill_id: 'skill_review', name: 'review-code' }],
            );
        });

        it('shows chips again for a restored draft', () => {
            render(<ChatInput onSend={vi.fn()} isStreaming={false} draft="/summarize the thread" onDraftConsumed={vi.fn()} />);

            expect(screen.getByTestId('composer-shortcuts')).toHaveTextContent('Skillsummarize');
        });

        it('refreshes the skill list when the list opens, at most once per interval', async () => {
            const user = userEvent.setup();
            skillsHook.refresh.mockClear();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
            const textarea = screen.getByPlaceholderText('Message Omnideck…');

            await user.type(textarea, '/rev');
            expect(skillsHook.refresh).toHaveBeenCalledTimes(1);

            await user.keyboard('{Escape}');
            await user.type(textarea, ' /sum');
            expect(skillsHook.refresh).toHaveBeenCalledTimes(1);
        });
    });
});
