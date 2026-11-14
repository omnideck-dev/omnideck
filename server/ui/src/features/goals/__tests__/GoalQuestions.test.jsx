import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatInput from '../../../components/ChatInput.jsx';

const question = (id, text, choices = []) => ({ id, question: text, choices, status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 });
const goal = () => ({
    id: 'goal-1', conversation_id: 'chat', revision: 2, paused: false, running: false,
    next: { kind: 'wait', question_ids: ['insurance', 'travel'] },
    questions: [question('insurance', 'Which insurance plan?', ['Aetna Dental PPO', 'Cigna Dental']), question('travel', 'How far can you travel?')],
});
const DRAFT_KEY = 'omnideck_goal_answers:chat:goal-1';
const savedDrafts = () => JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}');
beforeEach(() => localStorage.clear());

describe('goal questions in the composer', () => {
    it('hides questions for normal chat, preserves each draft, and reopens when a new question arrives', async () => {
        const user = userEvent.setup();
        const current = goal();
        const onSend = vi.fn();
        const view = render(<ChatInput goal={current} conversationId="chat" onSend={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Insurance draft');
        await user.click(screen.getByRole('button', { name: 'Hide' }));
        expect(screen.queryByLabelText('Goal questions')).not.toBeInTheDocument();
        expect(screen.getByText('2 questions for you · 1 answer drafted')).toBeVisible();
        await user.type(screen.getByRole('textbox'), 'Normal chat draft');
        await user.click(screen.getByRole('button', { name: 'Show goal questions' }));
        expect(screen.queryByText(/2 questions for you/)).not.toBeInTheDocument();
        expect(screen.getByRole('textbox')).toHaveValue('Insurance draft');
        await user.click(screen.getByRole('button', { name: 'Hide' }));
        expect(screen.getByRole('textbox')).toHaveValue('Normal chat draft');
        await user.click(screen.getByRole('button', { name: 'Send message' }));
        expect(onSend).toHaveBeenCalledWith('Normal chat draft', null);
        const revised = { ...current, questions: [...current.questions, question('date', 'Which day?')] };
        view.rerender(<ChatInput goal={revised} conversationId="chat" onSend={onSend} />);
        expect(screen.getByLabelText('Goal questions')).toBeVisible();
        expect(screen.getByRole('textbox')).toHaveValue('Insurance draft');
    });

    it('shows no draft count on the hidden row when nothing is drafted', async () => {
        const user = userEvent.setup();
        render(<ChatInput goal={goal()} conversationId="chat" onSend={vi.fn()} />);
        await user.click(screen.getByRole('button', { name: 'Hide' }));
        expect(screen.getByText('2 questions for you')).toBeVisible();
    });

    it('marks a picked choice and moves on without filling the text box', async () => {
        const user = userEvent.setup();
        render(<ChatInput goal={goal()} conversationId="chat" onSend={vi.fn()} />);
        await user.click(screen.getByRole('button', { name: 'Aetna Dental PPO' }));
        expect(screen.getByText('How far can you travel?')).toBeVisible();
        expect(screen.getByRole('textbox')).toHaveValue('');
        expect(screen.getByRole('button', { name: 'Question 1, answer drafted' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Question 2' })).toHaveAttribute('aria-current', 'true');
        await user.click(screen.getByRole('button', { name: 'Question 1, answer drafted' }));
        expect(screen.getByRole('textbox')).toHaveValue('');
        expect(screen.getByRole('button', { name: 'Aetna Dental PPO' })).toHaveAttribute('aria-pressed', 'true');
        expect(screen.getByRole('button', { name: 'Cigna Dental' })).toHaveAttribute('aria-pressed', 'false');
    });

    it('replaces a picked choice when the user types an answer', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        render(<ChatInput goal={goal()} conversationId="chat" onSendAnswers={onSend} />);
        await user.click(screen.getByRole('button', { name: 'Aetna Dental PPO' }));
        await user.click(screen.getByRole('button', { name: 'Question 1, answer drafted' }));
        await user.type(screen.getByRole('textbox'), 'Delta Dental');
        expect(screen.getByRole('button', { name: 'Aetna Dental PPO' })).toHaveAttribute('aria-pressed', 'false');
        await user.click(screen.getByRole('button', { name: 'Send answer' }));
        expect(onSend.mock.calls[0][1]).toEqual([{ question_id: 'insurance', question_revision: 1, question: 'Which insurance plan?', answer: 'Delta Dental' }]);
    });

    it('skips to the next question and keeps the skipped one open', async () => {
        const user = userEvent.setup();
        render(<ChatInput goal={goal()} conversationId="chat" onSend={vi.fn()} />);
        expect(screen.getByText('Question 1 of 2')).toBeVisible();
        await user.click(screen.getByRole('button', { name: 'Skip for now' }));
        expect(screen.getByText('How far can you travel?')).toBeVisible();
        expect(screen.getByText('Question 2 of 2')).toBeVisible();
        expect(screen.getByRole('button', { name: 'Question 1' })).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Skip for now' }));
        expect(screen.getByText('Which insurance plan?')).toBeVisible();
    });

    it('marks which questions have drafts', async () => {
        const user = userEvent.setup();
        render(<ChatInput goal={goal()} conversationId="chat" onSend={vi.fn()} />);
        const marks = screen.getByRole('group', { name: 'Questions' });
        expect(within(marks).getAllByRole('button').map((mark) => mark.getAttribute('aria-label'))).toEqual(['Question 1', 'Question 2']);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        expect(within(marks).getAllByRole('button').map((mark) => mark.getAttribute('aria-label'))).toEqual(['Question 1, answer drafted', 'Question 2']);
        expect(screen.queryByText(/ready to send/)).not.toBeInTheDocument();
    });

    it('keeps one reply box and sends all drafted answers with their question context', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        render(<ChatInput goal={goal()} conversationId="chat" onSendAnswers={onSend} />);
        expect(screen.getAllByRole('textbox')).toHaveLength(1);
        await user.click(screen.getByRole('button', { name: 'Aetna Dental PPO' }));
        expect(onSend).not.toHaveBeenCalled();
        await user.type(screen.getByRole('textbox'), 'Within 10 miles');
        await user.click(screen.getByRole('button', { name: 'Send 2 answers' }));
        expect(onSend).toHaveBeenCalledWith('goal-1', [
            { question_id: 'insurance', question_revision: 1, question: 'Which insurance plan?', answer: 'Aetna Dental PPO' },
            { question_id: 'travel', question_revision: 1, question: 'How far can you travel?', answer: 'Within 10 miles' },
        ]);
    });

    it('submits partial answers and leaves unanswered questions available', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        const current = goal();
        const { rerender } = render(<ChatInput goal={current} conversationId="chat" onSendAnswers={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Not sure');
        await user.click(screen.getByRole('button', { name: 'Question 2' }));
        expect(screen.getByRole('textbox')).toHaveValue('');
        await user.click(screen.getByRole('button', { name: 'Send answer' }));
        expect(onSend.mock.calls[0][1]).toHaveLength(1);
        const received = structuredClone(current);
        received.revision = 3;
        received.questions[0].answers.push({ answer: 'Not sure', question_revision: 1 });
        rerender(<ChatInput goal={received} conversationId="chat" onSendAnswers={onSend} />);
        expect(screen.getByText('How far can you travel?')).toBeVisible();
        expect(screen.queryByRole('group', { name: 'Questions' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Skip for now' })).not.toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Hide' }));
        expect(screen.getByText('1 question for you')).toBeVisible();
        rerender(<ChatInput goal={{ ...received, questions: [] }} conversationId="chat" onSendAnswers={onSend} />);
        expect(screen.queryByRole('button', { name: 'Show goal questions' })).not.toBeInTheDocument();
    });

    it('keeps drafts across remounts', async () => {
        const user = userEvent.setup();
        const current = goal();
        const first = render(<ChatInput goal={current} conversationId="chat" onSend={vi.fn()} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        first.unmount();
        render(<ChatInput goal={current} conversationId="chat" onSend={vi.fn()} />);
        expect(screen.getByRole('textbox')).toHaveValue('Aetna');
        expect(screen.getByRole('button', { name: 'Send answer' })).toBeEnabled();
    });

    it('drops saved drafts whose question changed or closed when they load', () => {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({
            insurance: { text: 'Aetna', choice: '', revision: 1 },
            travel: { text: 'Ten miles', choice: '', revision: 1 },
            gone: { text: 'Old answer', choice: '', revision: 1 },
        }));
        const current = goal();
        current.questions[0].revision = 2;
        current.questions[0].question = 'Which insurer and exact plan?';
        current.questions.push(question('gone', 'Withdrawn question'));
        current.questions[2].status = 'withdrawn';
        render(<ChatInput goal={current} conversationId="chat" onSend={vi.fn()} />);
        expect(screen.getByRole('textbox')).toHaveValue('');
        expect(screen.getByRole('button', { name: 'Question 2, answer drafted' })).toBeInTheDocument();
        expect(Object.keys(savedDrafts())).toEqual(['travel']);
    });

    it('clears sent drafts from storage when the send succeeds, before the goal is polled again', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn().mockResolvedValue({});
        const view = render(<ChatInput goal={goal()} conversationId="chat" onSendAnswers={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        await user.click(screen.getByRole('button', { name: 'Question 2' }));
        await user.type(screen.getByRole('textbox'), 'Ten miles');
        expect(Object.keys(savedDrafts())).toEqual(['insurance', 'travel']);
        await user.click(screen.getByRole('button', { name: 'Send 2 answers' }));
        await waitFor(() => expect(savedDrafts()).toEqual({}));
        view.unmount();
        expect(savedDrafts()).toEqual({});
    });

    it('offers a send action during an active run and does not label paused replies as resuming', async () => {
        const user = userEvent.setup();
        const current = goal();
        const onSend = vi.fn();
        const { rerender } = render(<ChatInput goal={current} isStreaming conversationId="chat" onSendAnswers={onSend} onStop={vi.fn()} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        await user.click(screen.getByRole('button', { name: 'Send answer', exact: true }));
        await waitFor(() => expect(onSend).toHaveBeenCalledOnce());
        const saved = structuredClone(current);
        saved.paused = true;
        saved.revision = 3;
        saved.questions[0].answers.push({ answer: 'Aetna', question_revision: 1 });
        rerender(<ChatInput goal={saved} conversationId="chat" onSendAnswers={onSend} />);
        expect(screen.getByRole('button', { name: 'Send answer', exact: true })).toBeInTheDocument();
        expect(screen.getByText('Your answers will be saved. The goal stays paused until you resume it.')).toBeVisible();
        expect(screen.queryByText(/Resuming/)).not.toBeInTheDocument();
    });

    it('reviews a changed question elsewhere in the carousel before sending the batch', async () => {
        const user = userEvent.setup();
        const current = goal();
        const onSend = vi.fn();
        const { rerender } = render(<ChatInput goal={current} conversationId="chat" onSendAnswers={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        await user.click(screen.getByRole('button', { name: 'Question 2' }));
        await user.type(screen.getByRole('textbox'), 'Ten miles');
        const changed = structuredClone(current);
        changed.questions[0].revision = 2;
        changed.questions[0].question = 'Which insurer and exact plan?';
        rerender(<ChatInput goal={changed} conversationId="chat" onSendAnswers={onSend} />);
        expect(screen.getByRole('button', { name: 'Send answer' })).toBeDisabled();
        await user.click(screen.getByRole('button', { name: 'Review answer' }));
        expect(screen.getByRole('textbox')).toHaveValue('Aetna');
        expect(screen.getByText(/The question changed/)).toBeVisible();
        await user.type(screen.getByRole('textbox'), ' Dental PPO');
        await user.click(screen.getByRole('button', { name: 'Send 2 answers' }));
        expect(onSend.mock.calls[0][1]).toEqual([
            { question_id: 'insurance', question_revision: 2, question: 'Which insurer and exact plan?', answer: 'Aetna Dental PPO' },
            { question_id: 'travel', question_revision: 1, question: 'How far can you travel?', answer: 'Ten miles' },
        ]);
    });

    it('sends steering as ordinary text and lets the agent keep the question open', async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        const current = goal();
        const { rerender } = render(<ChatInput goal={current} conversationId="chat" onSendAnswers={onSend} />);
        expect(screen.queryByRole('button', { name: 'Chat instead' })).not.toBeInTheDocument();
        await user.type(screen.getByRole('textbox'), 'Actually, look near my office');
        await user.keyboard('{Enter}');
        expect(onSend).toHaveBeenCalledWith('goal-1', [
            { question_id: 'insurance', question_revision: 1, question: 'Which insurance plan?', answer: 'Actually, look near my office' },
        ]);
        const reviewed = structuredClone(current);
        reviewed.questions[0].answers.push({ answer: 'Actually, look near my office', question_revision: 1 });
        reviewed.questions[0].reviewed_answer_count = 1;
        reviewed.questions[0].revision = 2;
        rerender(<ChatInput goal={reviewed} conversationId="chat" onSendAnswers={onSend} />);
        expect(screen.getByText('Which insurance plan?')).toBeVisible();
        await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue(''));
    });

    it('accepts another answer when the previous question is archived during the same run', async () => {
        const user = userEvent.setup();
        let finish;
        const onSend = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
        const current = goal();
        const { rerender } = render(<ChatInput goal={current} conversationId="chat" onSendAnswers={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Aetna');
        await user.click(screen.getByRole('button', { name: 'Send answer' }));
        rerender(<ChatInput goal={{ ...current, questions: [current.questions[1]] }} isStreaming conversationId="chat" onSendAnswers={onSend} />);
        await user.type(screen.getByRole('textbox'), 'Ten miles');
        expect(screen.getByRole('button', { name: 'Send answer', exact: true })).toBeEnabled();
        await act(async () => finish());
    });
});
