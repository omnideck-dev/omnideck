import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import GoalHeadline from '../GoalHeadline.jsx';
import GoalStatus from '../GoalStatus.jsx';
import GoalTransition from '../GoalTransition.jsx';
import { goalStatus } from '../goalStatus.js';
import styles from '../GoalTransition.module.css';
import statusStyles from '../GoalStatus.module.css';

const TIMESTAMP = '2026-10-23T14:00:00Z';
const divider = (transition, fields = {}) => ({
    id: transition, transition, step: '', questionCount: 0, timestamp: TIMESTAMP, resumeAt: null, ...fields,
});
const goal = (fields = {}) => ({
    id: 'g1', objective: 'Book the pavilion', paused: false, running: false,
    next: { kind: 'wait', question_ids: [] }, questions: [], plan: [], ...fields,
});

function iconOf(element) {
    return Array.from(element.querySelector('i').classList).find((name) => name.startsWith('bi-'));
}

describe('goal transition dividers', () => {
    it.each([
        ['scheduled', goal({ next: { kind: 'wake', id: 'w', at: '2099-01-01T00:00:00Z', reason: 'planned' } })],
        ['waiting', goal()],
        ['error', goal({ next: { kind: 'error', message: 'Failed' } })],
        ['completed', goal({ next: { kind: 'done', outcome: 'Booked' } })],
    ])('draws the %s divider with the matching status icon and tone', (transition, matching) => {
        const status = goalStatus(matching);
        render(<GoalTransition event={divider(transition, { resumeAt: '2099-01-01T00:00:00Z' })} />);
        const icon = screen.getByTestId('goal-transition').querySelector('i');
        expect(icon).toHaveClass(status.icon, styles[status.tone]);
    });

    it.each(['run'])('draws the %s divider in the Working tone', (transition) => {
        render(<GoalTransition event={divider(transition)} />);
        expect(screen.getByTestId('goal-transition').querySelector('i')).toHaveClass(styles.accent);
    });

    it.each([
        ['run', { step: 'Call the parks office' }, 'Goal run· Call the parks office'],
        ['waiting', { questionCount: 3 }, 'Waiting for you· 3 questions'],
        ['waiting', { questionCount: 1 }, 'Waiting for you· 1 question'],
        ['error', {}, 'Stopped by an error'],
        ['completed', {}, 'Goal done'],
    ])('describes the %s event in one line', (transition, fields, text) => {
        render(<GoalTransition event={divider(transition, fields)} />);
        expect(screen.getByTestId('goal-transition').querySelector(`.${styles.content}`)).toHaveTextContent(text);
    });

    it('shows a run divider with no step as "Goal run" alone', () => {
        render(<GoalTransition event={divider('run')} />);
        const row = screen.getByTestId('goal-transition');
        expect(row.querySelector(`.${styles.label}`)).toHaveTextContent('Goal run');
        expect(row.querySelector(`.${styles.detail}`)).toBeNull();
    });

    it('draws nothing for a kind it does not show', () => {
        const { container } = render(<GoalTransition event={divider('paused')} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('keeps the time in a class that stays hidden until hover', () => {
        render(<GoalTransition event={divider('completed')} />);
        const time = within(screen.getByTestId('goal-transition')).getByText((_, element) => element?.tagName === 'TIME');
        expect(time).toHaveClass(styles.time);
        expect(time).toHaveAttribute('dateTime', TIMESTAMP);
    });

    it('carries a copy of the time for the invisible spacer that keeps the label centered', () => {
        render(<GoalTransition event={divider('completed')} />);
        const time = within(screen.getByTestId('goal-transition')).getByText((_, element) => element?.tagName === 'TIME');
        expect(time.parentElement).toHaveClass(styles.content);
        expect(time.parentElement).toHaveAttribute('data-time', time.textContent);
    });
});

describe('one status everywhere', () => {
    it('leaves the status chip unlabelled so screen readers read its text', () => {
        render(<GoalStatus goal={goal({ paused: true })} />);
        expect(screen.getByTestId('goal-status')).not.toHaveAttribute('aria-label');
        expect(screen.getByTestId('goal-status')).toHaveAttribute('data-status', 'paused');
    });

    it.each([
        goal({ next: { kind: 'done', outcome: 'Booked' } }),
        goal({ paused: true }),
        goal({ running: true }),
        goal({ next: { kind: 'error', message: 'Failed' } }),
        goal({ next: { kind: 'wait', question_ids: ['a'] }, questions: [{ id: 'a', question: 'Q', choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 }] }),
        goal({ next: { kind: 'wake', id: 'w', at: '2099-01-01T00:00:00Z', reason: 'planned' } }),
    ])('renders the same text and tone in the status chip and the header (%#)', (input) => {
        const status = goalStatus(input);
        const chip = render(<GoalStatus goal={input} />);
        const chipStatus = chip.getByTestId('goal-status');
        expect(chipStatus).toHaveTextContent(status.label);
        expect(chipStatus).toHaveClass(statusStyles[status.tone]);
        expect(iconOf(chipStatus)).toBe(status.icon);
        chip.unmount();

        render(<GoalHeadline goal={input} onOpen={() => {}} />);
        const button = screen.getByTestId('goal-headline');
        expect(button).toHaveTextContent(status.label);
        expect(button.querySelector('i')).toHaveClass('bi-bullseye', statusStyles[status.tone]);
        for (const text of button.querySelectorAll('span')) expect(text).toHaveClass(statusStyles[status.tone]);
    });
});
