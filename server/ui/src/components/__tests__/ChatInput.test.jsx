import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import ChatInput from '../ChatInput.jsx';
import buttonStyles from '../primitives/Button.module.css';
import { formatRunTime } from '../../features/goals/goalStatus.js';

// Minimal 1x1 transparent PNG base64
const MOCK_BASE64_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAADElEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==';

describe('ChatInput', () => {
    it('renders textarea and buttons', () => {
        render(<ChatInput onSend={vi.fn()} isStreaming={false} />);

        expect(screen.getByPlaceholderText('Message Omnideck…')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Add to chat' })).toBeInTheDocument();
        expect(screen.getByLabelText('Send message')).toBeInTheDocument();
    });

    it('calls onSend with message when submitted', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, 'Hello world');
        await user.click(screen.getByLabelText('Send message'));

        expect(onSend).toHaveBeenCalledWith('Hello world', null);
    });

    describe('composer actions', () => {
        it('opens an accessible menu and keeps file selection on the existing input', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
            const trigger = screen.getByRole('button', { name: 'Add to chat' });
            expect(trigger).toHaveAttribute('aria-expanded', 'false');
            await user.click(trigger);
            const menu = screen.getByRole('menu', { name: 'Add to chat' });
            expect(trigger).toHaveAttribute('aria-controls', menu.id);
            const attach = screen.getByRole('menuitem', { name: 'Attach file' });
            expect(attach).toHaveFocus();
            expect(screen.queryByRole('menuitem', { name: /Goal/ })).not.toBeInTheDocument();
            const input = screen.getByLabelText('Choose files to attach');
            const click = vi.spyOn(input, 'click').mockImplementation(() => {});
            await user.click(attach);
            expect(click).toHaveBeenCalledOnce();
            expect(screen.queryByRole('menu')).not.toBeInTheDocument();
            expect(trigger).toHaveFocus();
            click.mockRestore();
            await user.upload(input, new File(['notes'], 'notes.txt', { type: 'text/plain' }));
            expect(await screen.findByTitle('notes.txt')).toBeInTheDocument();
        });

        it('navigates items with arrows, Home and End, and returns focus on Escape', async () => {
            const user = userEvent.setup();
            const onRequestGoal = vi.fn();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} />);
            const trigger = screen.getByRole('button', { name: 'Add to chat' });
            trigger.focus();
            await user.keyboard('{ArrowUp}');
            const goal = screen.getByRole('menuitem', { name: /Start a goal/ });
            const attach = screen.getByRole('menuitem', { name: 'Attach file' });
            expect(goal).toHaveFocus();
            await user.keyboard('{ArrowDown}');
            expect(attach).toHaveFocus();
            await user.keyboard('{End}');
            expect(goal).toHaveFocus();
            await user.keyboard('{Home}');
            expect(attach).toHaveFocus();
            await user.keyboard('{ArrowUp}');
            expect(goal).toHaveFocus();
            await user.keyboard('{Escape}');
            expect(screen.queryByRole('menu')).not.toBeInTheDocument();
            expect(trigger).toHaveFocus();
            expect(onRequestGoal).not.toHaveBeenCalled();
        });

        it('closes the menu when tabbing to the next composer control', async () => {
            const user = userEvent.setup();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={vi.fn()} />);
            await user.type(screen.getByRole('textbox'), 'Draft');
            await user.click(screen.getByRole('button', { name: 'Add to chat' }));
            await user.keyboard('{Tab}');
            expect(screen.queryByRole('menu')).not.toBeInTheDocument();
            expect(screen.getByRole('button', { name: 'Send message' })).toHaveFocus();
        });

        it('opens a blank goal from the menu without consuming draft text or attachments', async () => {
            const user = userEvent.setup();
            const onRequestGoal = vi.fn();
            const onSend = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} onRequestGoal={onRequestGoal} attachment={{ base64: 'YWJj', contentType: 'text/plain', filename: 'notes.txt' }} />);
            const textarea = screen.getByRole('textbox');
            await user.type(textarea, 'My unfinished question');
            await user.click(screen.getByRole('button', { name: 'Add to chat' }));
            await user.click(screen.getByRole('menuitem', { name: /Start a goal/ }));
            expect(onRequestGoal).toHaveBeenCalledWith({ objective: '', onStarted: expect.any(Function), onClosed: expect.any(Function) });
            expect(screen.queryByRole('menu')).not.toBeInTheDocument();
            await act(async () => onRequestGoal.mock.calls[0][0].onStarted());
            expect(textarea).toHaveValue('My unfinished question');
            expect(screen.getByTitle('notes.txt')).toBeInTheDocument();
            expect(onSend).not.toHaveBeenCalled();
            await act(async () => onRequestGoal.mock.calls[0][0].onClosed());
            expect(textarea).toHaveFocus();
        });

        it.each([{ isOffline: true }, { stopRequested: true }])('disables composer actions when unavailable: %j', async (state) => {
            const user = userEvent.setup();
            const onRequestGoal = vi.fn();
            const view = render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} />);
            await user.click(screen.getByRole('button', { name: 'Add to chat' }));
            expect(screen.getByRole('menu')).toBeInTheDocument();
            view.rerender(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} {...state} />);
            expect(screen.queryByRole('menu')).not.toBeInTheDocument();
            expect(screen.getByRole('button', { name: 'Add to chat' })).toBeDisabled();
            expect(onRequestGoal).not.toHaveBeenCalled();
        });
    });

    describe('/goal command', () => {
        it('picks /goal from the slash hint on the first Enter and opens the dialog on the next', async () => {
            const user = userEvent.setup();
            const onRequestGoal = vi.fn();
            const onSend = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} onRequestGoal={onRequestGoal} />);
            const textarea = screen.getByRole('textbox');
            await user.type(textarea, '/goal{Enter}');
            expect(textarea).toHaveValue('/goal ');
            expect(onRequestGoal).not.toHaveBeenCalled();
            await user.keyboard('{Enter}');
            expect(onSend).not.toHaveBeenCalled();
            expect(onRequestGoal).toHaveBeenCalledWith({ objective: '', onStarted: expect.any(Function), onClosed: expect.any(Function) });
            await act(async () => onRequestGoal.mock.calls[0][0].onStarted());
            expect(textarea).toHaveValue('');
        });

        it.each([
            { command: '/goal Plan our family trip', objective: 'Plan our family trip', enter: false },
            { command: '  /goal   Keep our schedule current  ', objective: 'Keep our schedule current', enter: true },
        ])('opens the goal dialog for $command without sending a message', async ({ command, objective, enter }) => {
            const user = userEvent.setup();
            const onRequestGoal = vi.fn();
            const onSend = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} onRequestGoal={onRequestGoal} />);
            const textarea = screen.getByRole('textbox');
            await user.type(textarea, command);
            if (enter) await user.keyboard('{Enter}');
            else await user.click(screen.getByRole('button', { name: 'Send message' }));
            expect(onSend).not.toHaveBeenCalled();
            expect(onRequestGoal).toHaveBeenCalledWith({ objective, onStarted: expect.any(Function), onClosed: expect.any(Function) });
            expect(textarea).toHaveValue(command);
            await act(async () => onRequestGoal.mock.calls[0][0].onStarted());
            expect(textarea).toHaveValue('');
        });

        it('preserves the command and files while the dialog is cancelled or fails, and retains files after success', async () => {
            const user = userEvent.setup();
            const onRequestGoal = vi.fn();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} attachment={{ base64: 'YWJj', contentType: 'text/plain', filename: 'schedule.txt' }} />);
            const textarea = screen.getByRole('textbox');
            await user.type(textarea, '/goal Plan this week{Enter}');
            expect(textarea).toHaveValue('/goal Plan this week');
            expect(screen.getByTitle('schedule.txt')).toBeInTheDocument();
            // Closing or failing the dialog never invokes the completion callback.
            await user.keyboard('{Enter}');
            expect(onRequestGoal).toHaveBeenCalledTimes(2);
            expect(textarea).toHaveValue('/goal Plan this week');
            await act(async () => onRequestGoal.mock.calls[1][0].onStarted());
            expect(textarea).toHaveValue('');
            expect(screen.getByTitle('schedule.txt')).toBeInTheDocument();
        });

        it('does not erase text edited after the goal dialog was opened', async () => {
            const user = userEvent.setup();
            const onRequestGoal = vi.fn();
            render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} conversationId="goal-command-draft" />);
            const textarea = screen.getByRole('textbox');
            await user.type(textarea, '/goal Update the calendar{Enter}');
            await user.clear(textarea);
            await user.type(textarea, 'Also include our weekend plans');
            await act(async () => onRequestGoal.mock.calls[0][0].onStarted());
            expect(textarea).toHaveValue('Also include our weekend plans');
            expect(localStorage.getItem('omnideck_chat_draft_v1:goal-command-draft')).toBe('Also include our weekend plans');
        });

        it.each(['/goals', '/goalkeeper', '/goal-and-more'])('sends %s as ordinary chat text', async (command) => {
            const user = userEvent.setup();
            const onSend = vi.fn();
            const onRequestGoal = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} onRequestGoal={onRequestGoal} />);
            await user.type(screen.getByRole('textbox'), `${command}{Enter}`);
            expect(onRequestGoal).not.toHaveBeenCalled();
            expect(onSend).toHaveBeenCalledWith(command, null);
        });

        it('keeps slash text ordinary when goals are disabled', async () => {
            const user = userEvent.setup();
            const onSend = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} />);
            await user.type(screen.getByRole('textbox'), '/goal Plan the trip{Enter}');
            expect(onSend).toHaveBeenCalledWith('/goal Plan the trip', null);
        });

        it('does not submit on Shift+Enter or while composing text', async () => {
            const user = userEvent.setup();
            const onSend = vi.fn();
            const onRequestGoal = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} onRequestGoal={onRequestGoal} />);
            const textarea = screen.getByRole('textbox');
            await user.type(textarea, '/goal{Shift>}{Enter}{/Shift}Plan the trip');
            fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true });
            expect(textarea).toHaveValue('/goal\nPlan the trip');
            expect(onRequestGoal).not.toHaveBeenCalled();
            expect(onSend).not.toHaveBeenCalled();
        });

        it('opens a goal during a running turn instead of sending a nudge', async () => {
            const user = userEvent.setup();
            const onSend = vi.fn();
            const onRequestGoal = vi.fn();
            render(<ChatInput onSend={onSend} onStop={vi.fn()} isStreaming onRequestGoal={onRequestGoal} />);
            await user.type(screen.getByRole('textbox'), '/goal Plan next month{Enter}');
            expect(onSend).not.toHaveBeenCalled();
            expect(onRequestGoal).toHaveBeenCalledWith({ objective: 'Plan next month', onStarted: expect.any(Function), onClosed: expect.any(Function) });
        });

        it('does not open a goal while offline', async () => {
            const onRequestGoal = vi.fn();
            const onSend = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} isOffline onRequestGoal={onRequestGoal} />);
            const textarea = screen.getByRole('textbox');
            fireEvent.change(textarea, { target: { value: '/goal Plan next month' } });
            fireEvent.keyDown(textarea, { key: 'Enter' });
            expect(onRequestGoal).not.toHaveBeenCalled();
            expect(onSend).not.toHaveBeenCalled();
            expect(textarea).toHaveValue('/goal Plan next month');
        });

        it('preserves pasted screenshots through goal creation and sends them with a later message', async () => {
            const user = userEvent.setup();
            const onSend = vi.fn();
            const onRequestGoal = vi.fn();
            render(<ChatInput onSend={onSend} isStreaming={false} onRequestGoal={onRequestGoal} />);
            const textarea = screen.getByRole('textbox');
            fireEvent.paste(textarea, {
                clipboardData: { items: [{ type: 'image/png', getAsFile: () => new File(['image'], 'clipboard.png', { type: 'image/png' }) }] },
            });
            await screen.findByTestId('attachment-image');
            await user.type(textarea, '/goal Organize my schedule{Enter}');
            await act(async () => onRequestGoal.mock.calls[0][0].onStarted());
            expect(screen.getByTestId('attachment-image')).toBeInTheDocument();
            await user.type(textarea, 'Use this schedule{Enter}');
            expect(onSend).toHaveBeenCalledWith('Use this schedule', expect.arrayContaining([
                expect.objectContaining({ content_type: 'image/png', filename: expect.stringMatching(/^screenshot_/), base64: expect.any(String) }),
            ]));
        });
    });

    it('trims whitespace from messages', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const textarea = screen.getByPlaceholderText('Message Omnideck…');
        await user.type(textarea, '  test message  ');
        await user.click(screen.getByLabelText('Send message'));

        expect(onSend).toHaveBeenCalledWith('test message', null);
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

        expect(onSend).toHaveBeenCalledWith('Test', null);
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

    it('shows stop button and the working placeholder when streaming', () => {
        render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming={true} />);

        expect(screen.getByLabelText('Stop generation')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Message the agent while it works…')).toBeInTheDocument();
        // While streaming the send button is replaced by stop.
        expect(screen.queryByLabelText('Send message')).not.toBeInTheDocument();
    });

    it('keeps streaming controls visible but disables messages after stop is requested', () => {
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

    it('uses the same working placeholder in every chat', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
            json: () => Promise.resolve([{ id: 'p1', name: 'Code Expert' }]),
        });
        try {
            render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming={true}
                selectedProfileId="p1" onProfileChange={vi.fn()} />);
            expect(await screen.findByPlaceholderText('Message the agent while it works…')).toBeInTheDocument();
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
        const fileInput = screen.getByLabelText('Choose files to attach');

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
        const fileInput = screen.getByLabelText('Choose files to attach');

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
        const fileInput = screen.getByLabelText('Choose files to attach');

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
        );
    });

    it('clears file after sending', async () => {
        const onSend = vi.fn();
        const user = userEvent.setup();
        render(<ChatInput onSend={onSend} isStreaming={false} />);

        const file = new File(['dummy'], 'test.png', { type: 'image/png' });
        const fileInput = screen.getByLabelText('Choose files to attach');

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
});

const goalWith = (fields = {}) => ({
    id: 'goal-1', conversation_id: 'chat', objective: 'Plan the reunion', revision: 3, paused: false, running: false,
    next: { kind: 'wait', question_ids: [] }, questions: [], plan: [], ...fields,
});
const openQuestion = (id, text) => ({ id, question: text, choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 });

describe('ChatInput goal entry points', () => {
    beforeEach(() => localStorage.clear());

    it('builds the Goal row from the shared menu item and labels it "Start a goal…" without a goal', async () => {
        const user = userEvent.setup();
        render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={vi.fn()} />);
        await user.click(screen.getByRole('button', { name: 'Add to chat' }));
        const goalItem = screen.getByRole('menuitem', { name: /Start a goal…/ });
        expect(goalItem).toHaveClass(buttonStyles.menuItem);
        expect(screen.getByRole('menuitem', { name: 'Attach file' })).toHaveClass(buttonStyles.menuItem);
        expect(goalItem).toHaveTextContent('/goal');
        expect(goalItem.querySelector('.bi-bullseye')).not.toBeNull();
    });

    it('labels the Goal row "Open goal" when the chat has an unfinished goal', async () => {
        const user = userEvent.setup();
        const onRequestGoal = vi.fn();
        render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} goal={goalWith()} />);
        await user.click(screen.getByRole('button', { name: 'Add to chat' }));
        expect(screen.queryByRole('menuitem', { name: /Start a goal/ })).not.toBeInTheDocument();
        await user.click(screen.getByRole('menuitem', { name: /Open goal/ }));
        expect(onRequestGoal).toHaveBeenCalledWith({ objective: '', onStarted: expect.any(Function), onClosed: expect.any(Function) });
    });

    it('offers "Start a goal…" again once the goal is done', async () => {
        const user = userEvent.setup();
        render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={vi.fn()} goal={goalWith({ next: { kind: 'done', outcome: 'Booked' } })} />);
        await user.click(screen.getByRole('button', { name: 'Add to chat' }));
        expect(screen.getByRole('menuitem', { name: /Start a goal…/ })).toBeInTheDocument();
    });

    it('keeps focus on the Goal item when a re-render passes a new onRequestGoal', async () => {
        const user = userEvent.setup();
        const view = render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={vi.fn()} />);
        screen.getByRole('button', { name: 'Add to chat' }).focus();
        await user.keyboard('{ArrowDown}');
        expect(screen.getByRole('menuitem', { name: 'Attach file' })).toHaveFocus();
        await user.keyboard('{ArrowDown}');
        const goalItem = screen.getByRole('menuitem', { name: /Start a goal/ });
        expect(goalItem).toHaveFocus();
        view.rerender(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={vi.fn()} />);
        expect(screen.getByRole('menuitem', { name: /Start a goal/ })).toHaveFocus();
    });

    it('shows a one-row slash hint for "/" and picks /goal with Enter', async () => {
        const user = userEvent.setup();
        const onRequestGoal = vi.fn();
        const onSend = vi.fn();
        render(<ChatInput onSend={onSend} isStreaming={false} onRequestGoal={onRequestGoal} />);
        const textarea = screen.getByRole('textbox');
        expect(screen.queryByTestId('slash-hint')).not.toBeInTheDocument();
        await user.type(textarea, '/');
        const hint = screen.getByTestId('slash-hint');
        expect(hint).toHaveTextContent('/goal');
        expect(hint).toHaveTextContent('Start a goal for this chat');
        expect(screen.getAllByRole('option')).toHaveLength(1);
        await user.keyboard('{Enter}');
        expect(textarea).toHaveValue('/goal ');
        expect(screen.queryByTestId('slash-hint')).not.toBeInTheDocument();
        expect(onSend).not.toHaveBeenCalled();
        expect(onRequestGoal).not.toHaveBeenCalled();
    });

    it('opens the existing goal from the slash hint when the chat has a goal', async () => {
        const user = userEvent.setup();
        const onRequestGoal = vi.fn();
        render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} goal={goalWith()} />);
        await user.type(screen.getByRole('textbox'), '/go');
        expect(screen.getByTestId('slash-hint')).toHaveTextContent("Open this chat's goal");
        await user.keyboard('{Enter}');
        expect(onRequestGoal).toHaveBeenCalledWith({ objective: '', onStarted: expect.any(Function), onClosed: expect.any(Function) });
    });

    it('hides the slash hint for other commands and after Escape', async () => {
        const user = userEvent.setup();
        render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={vi.fn()} />);
        const textarea = screen.getByRole('textbox');
        await user.type(textarea, '/x');
        expect(screen.queryByTestId('slash-hint')).not.toBeInTheDocument();
        await user.clear(textarea);
        await user.type(textarea, '/');
        expect(screen.getByTestId('slash-hint')).toBeInTheDocument();
        await user.keyboard('{Escape}');
        expect(screen.queryByTestId('slash-hint')).not.toBeInTheDocument();
        expect(textarea).toHaveValue('/');
    });

    it('keeps /goal text in the message box when the editor for an existing goal is cancelled', async () => {
        const user = userEvent.setup();
        const onRequestGoal = vi.fn();
        render(<ChatInput onSend={vi.fn()} isStreaming={false} onRequestGoal={onRequestGoal} goal={goalWith()} />);
        const textarea = screen.getByRole('textbox');
        await user.type(textarea, '/goal Find a dentist open on Saturdays{Enter}');
        expect(onRequestGoal).toHaveBeenCalledWith({ objective: 'Find a dentist open on Saturdays', onStarted: expect.any(Function), onClosed: expect.any(Function) });
        await act(async () => onRequestGoal.mock.calls[0][0].onClosed());
        expect(textarea).toHaveValue('/goal Find a dentist open on Saturdays');
    });

    it('uses the goal-run placeholder while a goal run is working', () => {
        render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming goal={goalWith({ running: true })} />);
        expect(screen.getByPlaceholderText('Message the agent while it works…')).toBeInTheDocument();
    });

    it('says in the Stop tooltip when the goal runs next', () => {
        const at = '2099-11-17T15:00:00Z';
        render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming
            goal={goalWith({ running: true, next: { kind: 'wake', id: 'w1', at, reason: 'planned' } })} />);
        expect(screen.getByTestId('chat-stop-btn')).toHaveAttribute('title', `Stops this run. The goal will still run ${formatRunTime(at)}.`);
    });

    it('says in the Stop tooltip that the goal will wait when no run is set', () => {
        render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming goal={goalWith({ running: true })} />);
        expect(screen.getByTestId('chat-stop-btn')).toHaveAttribute('title', 'Stops this run. The goal will wait for you.');
    });

    it('keeps the plain Stop tooltip without a goal', () => {
        render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming />);
        expect(screen.getByTestId('chat-stop-btn')).toHaveAttribute('title', 'Stop generation');
    });

    it('disables attaching while answering during a run and keeps an existing attachment', async () => {
        const user = userEvent.setup();
        const onSendAnswers = vi.fn();
        const goal = goalWith({ running: true, next: { kind: 'wait', question_ids: ['day'] }, questions: [openQuestion('day', 'Which day works?')] });
        render(<ChatInput onSend={vi.fn()} onSendAnswers={onSendAnswers} onStop={vi.fn()} isStreaming goal={goal} conversationId="chat"
            attachment={{ base64: 'YWJj', contentType: 'text/plain', filename: 'notes.txt' }} />);
        expect(screen.getByTitle('notes.txt')).toBeInTheDocument();
        expect(screen.getByText('Files can be sent after the agent finishes.')).toBeVisible();
        expect(screen.getByLabelText('Choose files to attach')).toBeDisabled();
        await user.click(screen.getByRole('button', { name: 'Add to chat' }));
        expect(screen.getByRole('menuitem', { name: 'Attach file' })).toBeDisabled();
        await user.keyboard('{Escape}');
        await user.type(screen.getByRole('textbox'), 'Tuesday');
        await user.click(screen.getByRole('button', { name: 'Send answer' }));
        expect(onSendAnswers).toHaveBeenCalledWith('goal-1', [{
            question_id: 'day', question_revision: 1, question: 'Which day works?', answer: 'Tuesday',
        }]);
        expect(screen.getByTitle('notes.txt')).toBeInTheDocument();
    });

    it('keeps attaching available while answering when no run is going', async () => {
        const user = userEvent.setup();
        const goal = goalWith({ next: { kind: 'wait', question_ids: ['day'] }, questions: [openQuestion('day', 'Which day works?')] });
        render(<ChatInput onSend={vi.fn()} isStreaming={false} goal={goal} conversationId="chat" />);
        expect(screen.getByLabelText('Choose files to attach')).toBeEnabled();
        await user.click(screen.getByRole('button', { name: 'Add to chat' }));
        expect(screen.getByRole('menuitem', { name: 'Attach file' })).toBeEnabled();
    });

    it('keeps Send off after a successful send until the goal shows the saved answer', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn().mockResolvedValue(undefined);
        const goal = goalWith({ next: { kind: 'wait', question_ids: ['day', 'place'] },
            questions: [openQuestion('day', 'Which day works?'), openQuestion('place', 'Which park?')] });
        const view = render(<ChatInput onSendAnswers={onSend} isStreaming={false} goal={goal} conversationId="chat" />);
        await user.type(screen.getByRole('textbox'), 'Tuesday');
        await user.click(screen.getByRole('button', { name: 'Send answer' }));
        await waitFor(() => expect(onSend).toHaveBeenCalledOnce());
        const sending = screen.getByRole('button', { name: 'Sending…' });
        expect(sending).toBeDisabled();
        await user.click(sending);
        expect(onSend).toHaveBeenCalledOnce();
        const saved = structuredClone(goal);
        saved.revision = 4;
        saved.questions[0].answers.push({ answer: 'Tuesday', question_revision: 1 });
        view.rerender(<ChatInput onSendAnswers={onSend} isStreaming={false} goal={saved} conversationId="chat" />);
        expect(screen.queryByRole('button', { name: 'Sending…' })).not.toBeInTheDocument();
        expect(screen.getByText('Which park?')).toBeVisible();
        await user.type(screen.getByRole('textbox'), 'Zilker');
        expect(screen.getByRole('button', { name: 'Send answer' })).toBeEnabled();
    });

    it('turns Send back on and keeps the drafts when the send is rejected', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn().mockRejectedValue(new Error('Your answers were not sent.'));
        const goal = goalWith({ next: { kind: 'wait', question_ids: ['day', 'place'] },
            questions: [openQuestion('day', 'Which day works?'), openQuestion('place', 'Which park?')] });
        render(<ChatInput onSendAnswers={onSend} isStreaming={false} goal={goal} conversationId="chat" />);
        await user.type(screen.getByRole('textbox'), 'Tuesday');
        await user.click(screen.getByRole('button', { name: 'Question 2' }));
        await user.type(screen.getByRole('textbox'), 'Zilker');
        await user.click(screen.getByRole('button', { name: 'Send 2 answers' }));
        await waitFor(() => expect(screen.getByRole('button', { name: 'Send 2 answers' })).toBeEnabled());
        expect(onSend).toHaveBeenCalledOnce();
        expect(screen.getByRole('textbox')).toHaveValue('Zilker');
        await user.click(screen.getByRole('button', { name: 'Question 1, answer drafted' }));
        expect(screen.getByRole('textbox')).toHaveValue('Tuesday');
    });
});
