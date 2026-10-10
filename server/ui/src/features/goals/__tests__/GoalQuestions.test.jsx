import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatInput from '../../../components/ChatInput.jsx';
import { GoalQuestionTranscript } from '../GoalQuestions.jsx';

const question = (id, text, choices = []) => ({ id, question: text, choices, status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 });
const goal = () => ({ id: 'goal-1', status: 'needs_input', revision: 2, questions: [question('insurance', 'Which insurance plan?', ['Aetna Dental PPO']), question('travel', 'How far can you travel?')] });
beforeEach(() => localStorage.clear());

describe('goal questions in the composer', () => {
    it('keeps one reply box, preserves carousel drafts, and submits linked answers together', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        render(<ChatInput goal={goal()} conversationId="chat" onSend={onSend} />);
        expect(screen.getAllByRole('textbox')).toHaveLength(1);
        await user.click(screen.getByRole('button', { name: 'Aetna Dental PPO' }));
        expect(onSend).not.toHaveBeenCalled();
        await user.click(screen.getByRole('button', { name: 'Next question' }));
        await user.type(screen.getByRole('textbox'), 'Within 10 miles');
        await user.click(screen.getByRole('button', { name: 'Previous question' }));
        expect(screen.getByRole('textbox')).toHaveValue('Aetna Dental PPO');
        await user.click(screen.getByRole('button', { name: 'Send answers & resume' }));
        expect(onSend).toHaveBeenCalledWith(expect.stringContaining('[travel] How far can you travel?\nWithin 10 miles'), null, {
            goal_id: 'goal-1', answers: [
                { question_id: 'insurance', question_revision: 1, answer: 'Aetna Dental PPO' },
                { question_id: 'travel', question_revision: 1, answer: 'Within 10 miles' },
            ],
        });
    });

    it('submits partial answers and leaves unanswered questions available', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        const current = goal();
        const { rerender } = render(<ChatInput goal={current} conversationId="chat" onSend={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Not sure');
        await user.click(screen.getByRole('button', { name: 'Send answers & resume' }));
        expect(onSend.mock.calls[0][2].answers).toHaveLength(1);
        const received = structuredClone(current);
        received.questions[0].answers.push({ answer: 'Not sure', question_revision: 1 });
        rerender(<ChatInput goal={received} conversationId="chat" onSend={onSend} />);
        expect(screen.getByText('How far can you travel?')).toBeVisible();
        expect(screen.queryByRole('button', { name: 'Next question' })).not.toBeInTheDocument();
    });

    it('preserves drafts across remounts and requires review when question wording changes', async () => {
        const user = userEvent.setup();
        const current = goal();
        const first = render(<ChatInput goal={current} conversationId="chat" onSend={vi.fn()} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        first.unmount();
        current.questions[0].revision = 2;
        current.questions[0].question = 'Which insurer and exact plan?';
        render(<ChatInput goal={current} conversationId="chat" onSend={vi.fn()} />);
        expect(screen.getByRole('textbox')).toHaveValue('Aetna');
        expect(screen.getByRole('button', { name: 'Send answers & resume' })).toBeDisabled();
        await user.type(screen.getByRole('textbox'), ' Dental PPO');
        expect(screen.getByRole('button', { name: 'Send answers & resume' })).toBeEnabled();
    });

    it('offers a send action during an active run and does not label paused replies as resuming', async () => {
        const user = userEvent.setup();
        const current = goal();
        const onSend = vi.fn();
        const { rerender } = render(<ChatInput goal={current} isStreaming conversationId="chat" onSend={onSend} onStop={vi.fn()} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        await user.click(screen.getByRole('button', { name: 'Send answers', exact: true }));
        await waitFor(() => expect(onSend).toHaveBeenCalledOnce());
        rerender(<ChatInput goal={{ ...current, status: 'paused' }} conversationId="chat" onSend={onSend} />);
        expect(screen.getByRole('button', { name: 'Send answers', exact: true })).toBeInTheDocument();
        expect(screen.getByText(/goal stays paused/)).toBeVisible();
    });

    it('lets ordinary chat continue while preserving question drafts', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        render(<ChatInput goal={goal()} conversationId="chat" onSend={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        await user.click(screen.getByRole('button', { name: 'Chat instead' }));
        await user.type(screen.getByRole('textbox'), 'Actually, look near my office');
        await user.keyboard('{Enter}');
        expect(onSend).toHaveBeenCalledWith('Actually, look near my office', null);
        await user.click(screen.getByRole('button', { name: 'Answer questions' }));
        expect(screen.getByRole('textbox')).toHaveValue('Aetna');
    });

    it('accepts another answer when the previous question is archived during the same run', async () => {
        const user = userEvent.setup();
        let finish;
        const onSend = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
        const current = goal();
        const { rerender } = render(<ChatInput goal={current} conversationId="chat" onSend={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        await user.click(screen.getByRole('button', { name: 'Send answers & resume' }));
        rerender(<ChatInput goal={{ ...current, questions: [current.questions[1]] }} isStreaming conversationId="chat" onSend={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Ten miles');
        expect(screen.getByRole('button', { name: 'Send answers', exact: true })).toBeEnabled();
        await act(async () => finish());
    });

    it('retains resolved and withdrawn question updates in the transcript', () => {
        render(<GoalQuestionTranscript content={JSON.stringify({ question_updates: [
            { ...question('insurance', 'Which insurance plan?'), status: 'withdrawn' },
            { ...question('travel', 'How far can you travel?'), status: 'resolved' },
        ] })} />);
        expect(screen.getByText('No longer needed')).toBeVisible();
        expect(screen.getByText('Resolved')).toBeVisible();
    });
});
