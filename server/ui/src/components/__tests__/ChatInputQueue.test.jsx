import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import ChatInput from '../ChatInput.jsx';

const question = (id, text) => ({ id, question: text, choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 });
const goal = {
    id: 'goal-1', conversation_id: 'chat', revision: 2, paused: false, running: true,
    next: { kind: 'wait', question_ids: ['day'] }, questions: [question('day', 'Which day works?')],
};
const answer = (text) => ({
    type: 'goal_question', goal_id: 'goal-1', question_id: 'day', question_revision: 1, question: 'Which day works?', answer: text,
});

beforeEach(() => localStorage.clear());

it('shows queued messages above the message box and hides the strip when empty', () => {
    const queue = [
        { id: 'n1', content: 'Also check Thursday', context: [] },
        { id: 'n2', content: '', context: [answer('Tuesday')] },
    ];
    const view = render(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming queue={queue} />);
    const strip = screen.getByRole('region', { name: "Queued for the agent's next step" });
    expect(strip).toHaveTextContent("Queued for the agent's next step");
    expect(within(strip).getByText('Also check Thursday')).toBeVisible();
    expect(within(strip).getByText('Answers to 1 question')).toBeVisible();
    expect(within(strip).getAllByRole('button', { name: 'Remove queued message' })).toHaveLength(2);

    view.rerender(<ChatInput onSend={vi.fn()} onStop={vi.fn()} isStreaming queue={[]} />);
    expect(screen.queryByTestId('queue-strip')).not.toBeInTheDocument();
});

it('counts answers to several questions', () => {
    const second = { ...answer('Zilker'), question_id: 'place' };
    render(<ChatInput onSend={vi.fn()} isStreaming queue={[{ id: 'n1', content: '', context: [answer('Tuesday'), second] }]} />);
    expect(screen.getByText('Answers to 2 questions')).toBeVisible();
});

it('removes a queued message with its remove button', async () => {
    const user = userEvent.setup();
    const onRemoveQueued = vi.fn().mockResolvedValue({ ok: true });
    render(<ChatInput onSend={vi.fn()} isStreaming queue={[{ id: 'n1', content: 'Later', context: [] }]} onRemoveQueued={onRemoveQueued} />);
    await user.click(screen.getByRole('button', { name: 'Remove queued message' }));
    expect(onRemoveQueued).toHaveBeenCalledWith('n1');
    expect(screen.getByRole('textbox')).toHaveValue('');
});

it('takes a clicked message out of the queue and back into the box to edit', async () => {
    const user = userEvent.setup();
    const onRemoveQueued = vi.fn().mockResolvedValue({ ok: true });
    render(<ChatInput onSend={vi.fn()} isStreaming queue={[{ id: 'n1', content: 'Also check Thursday', context: [] }]} onRemoveQueued={onRemoveQueued} />);
    await user.click(screen.getByRole('button', { name: 'Also check Thursday' }));
    expect(onRemoveQueued).toHaveBeenCalledWith('n1');
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue('Also check Thursday'));
});

it('leaves the box alone when the agent already read the clicked message', async () => {
    const user = userEvent.setup();
    const onRemoveQueued = vi.fn().mockResolvedValue({ ok: false, status: 409 });
    render(<ChatInput onSend={vi.fn()} isStreaming queue={[{ id: 'n1', content: 'Too late', context: [] }]} onRemoveQueued={onRemoveQueued} />);
    await user.click(screen.getByRole('button', { name: 'Too late' }));
    await waitFor(() => expect(onRemoveQueued).toHaveBeenCalled());
    expect(screen.getByRole('textbox')).toHaveValue('');
});

it('puts returned text back in the message box, one per line', async () => {
    const onReturnedConsumed = vi.fn();
    const user = userEvent.setup();
    const view = render(<ChatInput onSend={vi.fn()} isStreaming={false} onReturnedConsumed={onReturnedConsumed} />);
    await user.type(screen.getByRole('textbox'), 'Draft');
    view.rerender(<ChatInput onSend={vi.fn()} isStreaming={false} onReturnedConsumed={onReturnedConsumed}
        returned={[{ id: 'n1', content: 'First', context: [] }, { id: 'n2', content: 'Second', context: [] }]} />);
    expect(screen.getByRole('textbox')).toHaveValue('Draft\nFirst\nSecond');
    expect(onReturnedConsumed).toHaveBeenCalledWith(['n1', 'n2']);
});

it('locks the question card while its answers are queued', () => {
    render(<ChatInput onSend={vi.fn()} onSendAnswers={vi.fn()} onStop={vi.fn()} isStreaming goal={goal} conversationId="chat"
        queue={[{ id: 'n1', content: '', context: [answer('Tuesday')] }]} />);
    const card = screen.getByRole('region', { name: 'Goal questions' });
    expect(within(card).getByRole('status')).toHaveTextContent("Queued for the agent's next step");
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send answer' })).toBeDisabled();
});

it('puts returned answers back into the question card as drafts', async () => {
    const onReturnedConsumed = vi.fn();
    const queued = { id: 'n1', content: '', context: [answer('Tuesday')] };
    const view = render(<ChatInput onSend={vi.fn()} onSendAnswers={vi.fn()} isStreaming goal={goal} conversationId="chat" queue={[queued]} />);
    expect(screen.getByRole('textbox')).toBeDisabled();
    view.rerender(<ChatInput onSend={vi.fn()} onSendAnswers={vi.fn()} isStreaming={false} goal={goal} conversationId="chat"
        returned={[queued]} onReturnedConsumed={onReturnedConsumed} />);
    expect(screen.getByRole('textbox')).toBeEnabled();
    expect(screen.getByRole('textbox')).toHaveValue('Tuesday');
    expect(screen.getByRole('button', { name: 'Send answer' })).toBeEnabled();
    expect(onReturnedConsumed).toHaveBeenCalledWith(['n1']);
});

it('sends a message while the agent works and keeps attaching off', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} onStop={vi.fn()} isStreaming />);
    expect(screen.getByLabelText('Choose files to attach')).toBeDisabled();
    await user.type(screen.getByRole('textbox'), 'Also check Thursday{Enter}');
    expect(onSend).toHaveBeenCalledWith('Also check Thursday', null);
    expect(screen.getByRole('textbox')).toHaveValue('');
});
