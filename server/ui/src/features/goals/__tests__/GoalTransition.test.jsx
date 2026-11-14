import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import GoalHeadline from '../GoalHeadline.jsx';
import GoalStatus from '../GoalStatus.jsx';
import GoalTransition, { DayHeader } from '../GoalTransition.jsx';
import { goalStatus } from '../goalStatus.js';
import styles from '../GoalTransition.module.css';
import statusStyles from '../GoalStatus.module.css';

const TIMESTAMP = '2026-10-23T14:00:00Z';
const divider = (transition, fields = {}) => ({
    id: transition, transition, objective: '', step: '', questionCount: 0, timestamp: TIMESTAMP, resumeAt: null, ...fields,
});
const goal = (fields = {}) => ({
    id: 'g1', objective: 'Book the pavilion', paused: false, running: false,
    next: { kind: 'wait', question_ids: [] }, questions: [], plan: [], ...fields,
});

function iconOf(element) {
    return Array.from(element.querySelector('i').classList).find((name) => name.startsWith('bi-'));
}

describe('goal transition dividers', () => {
    // Each divider kind takes the icon and tone of its row in the status table.
    it.each([
        ['paused', goal({ paused: true })],
        ['scheduled', goal({ next: { kind: 'wake', id: 'w', at: '2099-01-01T00:00:00Z', reason: 'planned' } })],
        ['waiting', goal()],
        ['error', goal({ next: { kind: 'error', message: 'Failed' } })],
        ['completed', goal({ next: { kind: 'done', outcome: 'Booked' } })],
        ['cancelled', goal({ next: { kind: 'cancelled' } })],
    ])('draws the %s divider with the matching status icon and tone', (transition, matching) => {
        const status = goalStatus(matching);
        render(<GoalTransition event={divider(transition, { resumeAt: '2099-01-01T00:00:00Z' })} />);
        const icon = screen.getByTestId('goal-transition').querySelector('i');
        expect(icon).toHaveClass(status.icon, styles[status.tone]);
    });

    it.each(['started', 'run', 'resumed', 'reopened'])('draws the %s divider in the Working tone', (transition) => {
        render(<GoalTransition event={divider(transition)} />);
        expect(screen.getByTestId('goal-transition').querySelector('i')).toHaveClass(styles.accent);
    });

    it.each([
        ['started', { objective: 'Book the pavilion for Saturday' }, 'Goal started· Book the pavilion for Saturday'],
        ['run', { step: 'Call the parks office' }, 'Goal run· Call the parks office'],
        ['waiting', { questionCount: 3 }, 'Waiting for you· 3 questions'],
        ['waiting', { questionCount: 1 }, 'Waiting for you· 1 question'],
        ['error', {}, 'Stopped by an error'],
        ['completed', {}, 'Goal done'],
        ['cancelled', {}, 'Goal cancelled'],
        ['reopened', {}, 'Goal reopened'],
        ['paused', {}, 'Paused'],
        ['resumed', {}, 'Resumed'],
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

    it('puts the start divider objective in the one-line ellipsis slot', () => {
        const objective = 'Book the pavilion '.repeat(20).trim();
        render(<GoalTransition event={divider('started', { objective })} />);
        const detail = screen.getByTestId('goal-transition').querySelector(`.${styles.detail}`);
        expect(detail).toHaveTextContent(objective);
        expect(detail.querySelectorAll('br, p, div')).toHaveLength(0);
    });

    it('keeps the time in a class that stays hidden until hover', () => {
        render(<GoalTransition event={divider('paused')} />);
        const time = within(screen.getByTestId('goal-transition')).getByText((_, element) => element?.tagName === 'TIME');
        expect(time).toHaveClass(styles.time);
        expect(time).toHaveAttribute('dateTime', TIMESTAMP);
    });

    it('carries a copy of the time for the invisible spacer that keeps the label centered', () => {
        render(<GoalTransition event={divider('paused')} />);
        const time = within(screen.getByTestId('goal-transition')).getByText((_, element) => element?.tagName === 'TIME');
        expect(time.parentElement).toHaveClass(styles.content);
        expect(time.parentElement).toHaveAttribute('data-time', time.textContent);
    });

    it('labels a day header with the day', () => {
        const today = new Date();
        render(<DayHeader timestamp={today.toISOString()} />);
        expect(screen.getByTestId('day-header')).toHaveTextContent('Today');
        expect(screen.getByRole('separator', { name: 'Today' })).toBeInTheDocument();
    });
});

describe('one status everywhere', () => {
    it.each([
        goal({ next: { kind: 'done', outcome: 'Booked' } }),
        goal({ paused: true }),
        goal({ running: true }),
        goal({ next: { kind: 'error', message: 'Failed' } }),
        goal({ next: { kind: 'wait', question_ids: ['a'] }, questions: [{ id: 'a', question: 'Q', choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 }] }),
        goal({ next: { kind: 'wake', id: 'w', at: '2099-01-01T00:00:00Z', reason: 'planned' } }),
    ])('renders the same text and icon in the status chip and the header (%#)', (input) => {
        const status = goalStatus(input);
        const chip = render(<GoalStatus goal={input} />);
        const chipStatus = chip.getByTestId('goal-status');
        expect(chipStatus).toHaveTextContent(status.label);
        expect(chipStatus).toHaveClass(statusStyles[status.tone]);
        expect(iconOf(chipStatus)).toBe(status.icon);
        chip.unmount();

        render(<GoalHeadline goal={input} onOpen={() => {}} />);
        const [full, short] = screen.getAllByTestId('goal-status');
        expect(full).toHaveTextContent(status.label);
        expect(short).toHaveTextContent(status.shortLabel);
        expect(short).toHaveClass(statusStyles[status.tone]);
        expect(iconOf(full)).toBe(status.icon);
        expect(iconOf(short)).toBe(status.icon);
    });
});
