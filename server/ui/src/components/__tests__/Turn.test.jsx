import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Turn from '../Turn.jsx';
import { projectTurns } from '../../features/conversation/events/projectTurns.js';
import { formatRunTime } from '../../features/goals/goalStatus.js';

const _turn = (children) => ({
    id: 'turn_0', agentId: 'root.test.1', children,
});
const _userPrompt = (content, opts = {}) => ({
    kind: 'user_prompt',
    id: opts.id || 'um1',
    content,
    attachments: opts.attachments || [],
    isNudge: !!opts.isNudge,
});
const _iteration = (id, opts = {}) => ({
    kind: 'iteration',
    id,
    iterationIndex: opts.idx ?? 0,
    content: opts.content || '',
    thinking: opts.thinking || '',
    toolCalls: opts.toolCalls || [],
});
const _compaction = (id, opts = {}) => ({
    kind: 'compaction',
    id,
    summaryText: opts.summary || 'sum',
    userIntentSummary: opts.intent || '',
    stats: opts.stats || null,
    timestamp: '2026-01-01T00:00:00',
});

describe('Turn', () => {
    it.each(['planned', 'run_now', 'retry', 'interrupted'])('shows a "Goal run" divider for a %s wakeup and hides the wake note', (reason) => {
        const [turn] = projectTurns([
            { type: 'agent_started', id: 'start', agent_id: 'root.test.1', depth: 0, agent_name: 'Test' },
            { type: 'goal', id: 'wake-1', agent_id: 'root.test.1', depth: 0, goal_id: 'g1',
                data: { kind: 'wakeup', wake_id: 'w1', reason, step: 'Check the school calendar' } },
            { type: 'iteration', id: 'iter1', agent_id: 'root.test.1', depth: 0, content: 'I checked the new dates.' },
        ]);
        expect(turn.children.map(child => child.kind)).toEqual(['goal_transition', 'iteration']);
        render(<Turn turn={turn} />);
        const divider = screen.getByTestId('goal-transition');
        expect(divider).toHaveAttribute('data-transition', 'run');
        expect(divider).toHaveTextContent('Goal run· Check the school calendar');
        expect(divider).not.toHaveTextContent(reason);
        expect(screen.queryByTestId('message-user')).not.toBeInTheDocument();
        expect(screen.getByTestId('message-assistant')).toHaveTextContent('I checked the new dates.');
    });
    it('returns null for missing turn', () => {
        const { container } = render(<Turn turn={null} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('renders a single user_prompt + iteration as message-user + message-assistant', () => {
        const turn = _turn([
            _userPrompt('hi'),
            _iteration('iter1', { content: 'hello back' }),
        ]);
        render(<Turn turn={turn} />);
        expect(screen.getByTestId('message-user')).toHaveTextContent('hi');
        expect(screen.getByTestId('message-assistant')).toHaveTextContent('hello back');
    });

    it('shows a thinking placeholder while streaming before any assistant output', () => {
        const turn = _turn([_userPrompt('hi')]);
        render(<Turn turn={turn} streaming />);
        expect(screen.getByTestId('ephemeral-status')).toHaveTextContent('Thinking');
    });

    it('shows no placeholder when the turn is not streaming', () => {
        const turn = _turn([_userPrompt('hi')]);
        render(<Turn turn={turn} streaming={false} />);
        expect(screen.queryByTestId('ephemeral-status')).toBeNull();
    });

    it('renders an error child as a turn-error block with the message', () => {
        const turn = _turn([
            _userPrompt('do it'),
            { kind: 'error', id: 'e1', message: 'usage limit reached', retryable: false },
        ]);
        render(<Turn turn={turn} />);
        const err = screen.getByTestId('turn-error');
        expect(err).toHaveTextContent('usage limit reached');
    });

    it('merges consecutive iterations into one assistant element', () => {
        const turn = _turn([
            _userPrompt('go'),
            _iteration('iter1', { content: 'a' }),
            _iteration('iter2', { content: 'b' }),
            _iteration('iter3', { content: 'c' }),
        ]);
        render(<Turn turn={turn} />);
        const assistants = screen.getAllByTestId('message-assistant');
        expect(assistants).toHaveLength(1);
        const text = assistants[0].textContent;
        expect(text).toContain('a');
        expect(text).toContain('b');
        expect(text).toContain('c');
    });

    it('splits the assistant element when a compaction sits between iterations', () => {
        const turn = _turn([
            _userPrompt('go'),
            _iteration('iter1', { content: 'pre' }),
            _compaction('c1', { summary: 'compacted' }),
            _iteration('iter2', { content: 'post' }),
        ]);
        render(<Turn turn={turn} />);
        const assistants = screen.getAllByTestId('message-assistant');
        expect(assistants).toHaveLength(2);
        expect(assistants[0].textContent).toContain('pre');
        expect(assistants[1].textContent).toContain('post');
        expect(screen.getByTestId('compaction-chip')).toBeInTheDocument();
    });

    it('renders compaction-only (no following iterations) without a trailing assistant element', () => {
        const turn = _turn([
            _userPrompt('go'),
            _iteration('iter1', { content: 'pre' }),
            _compaction('c1'),
        ]);
        render(<Turn turn={turn} />);
        const assistants = screen.getAllByTestId('message-assistant');
        expect(assistants).toHaveLength(1);
        expect(screen.getByTestId('compaction-chip')).toBeInTheDocument();
    });

    it('renders multiple user_prompts (nudges) as separate message-user elements', () => {
        const turn = _turn([
            _userPrompt('first', { id: 'u1' }),
            _iteration('iter1', { content: 'a' }),
            _userPrompt('nudge', { id: 'u2', isNudge: true }),
            _iteration('iter2', { content: 'b' }),
        ]);
        render(<Turn turn={turn} />);
        const users = screen.getAllByTestId('message-user');
        expect(users).toHaveLength(2);
        expect(users[0]).toHaveTextContent('first');
        expect(users[1]).toHaveTextContent('nudge');
    });

    it('exposes data-testid="turn" and data-turn-id', () => {
        const turn = _turn([
            _userPrompt('go'),
            _iteration('iter1', { content: 'ok' }),
        ]);
        render(<Turn turn={turn} />);
        const el = screen.getByTestId('turn');
        expect(el).toHaveAttribute('data-turn-id', 'turn_0');
    });
});


describe('Turn ephemeral status (streaming "Calling X…" indicator)', () => {
    it('shows "Calling X…" when the last entry is a tool_call', () => {
        // The indicator is driven by the last entry in the entries list,
        // not by matching tool_call ids against tool_result events. This
        // makes it immune to React batching: when a tool executes quickly,
        // the iteration event and its tool_result arrive in the same
        // render, but the last entry is still the tool_call.
        const turn = _turn([
            _userPrompt('run a thing'),
            _iteration('i1', {
                content: 'sure', toolCalls: [
                    { id: 'tc1', name: 'run_bash_cmd' },
                ],
            }),
        ]);
        render(<Turn turn={turn} streaming />);
        expect(screen.getByTestId('ephemeral-status')).toHaveTextContent(
            'Calling run_bash_cmd…',
        );
    });

    it('shows the last tool call when multiple tools are in one iteration', () => {
        const turn = _turn([
            _userPrompt('run a thing'),
            _iteration('i1', {
                content: 'sure', toolCalls: [
                    { id: 'tc1', name: 'run_bash_cmd' },
                    { id: 'tc2', name: 'write_file' },
                ],
            }),
        ]);
        render(<Turn turn={turn} streaming />);
        expect(screen.getByTestId('ephemeral-status')).toHaveTextContent(
            'Calling write_file…',
        );
    });

    it('keeps showing "Calling X…" even after the tool_result arrives', () => {
        // This is the key fix: the old approach matched tool_call ids
        // against tool_result events and fell back to "Thinking…" as soon
        // as the result landed. When the result arrived in the same React
        // batch as the iteration event, "Calling X…" never rendered at all.
        // The lastEntry approach shows "Calling X…" until the next
        // iteration starts streaming thinking/content.
        const turn = _turn([
            _userPrompt('run a thing'),
            _iteration('i1', {
                content: 'sure', toolCalls: [{ id: 'tc1', name: 'run_bash_cmd' }],
            }),
            { kind: 'tool_result', id: 'tr1', toolCallId: 'tc1', toolName: '', content: '' },
        ]);
        render(<Turn turn={turn} streaming />);
        expect(screen.getByTestId('ephemeral-status')).toHaveTextContent(
            'Calling run_bash_cmd…',
        );
    });

    it('shows "Thinking…" when the last entry is thinking', () => {
        const turn = _turn([
            _userPrompt('run a thing'),
            _iteration('i1', { thinking: 'planning' }),
        ]);
        render(<Turn turn={turn} streaming />);
        expect(screen.getByTestId('ephemeral-status')).toHaveTextContent(
            'Thinking…',
        );
    });

    it('skips spawn_agent — the SpawnCard owns that visual', () => {
        // spawn_agent runs the whole sub-agent lifecycle, which can be
        // minutes long. The chat shouldn't say "Calling spawn_agent…"
        // the entire time.
        const turn = _turn([
            _userPrompt('delegate'),
            _iteration('i1', {
                thinking: 'planning', toolCalls: [
                    { id: 'tc-spawn', name: 'spawn_agent' },
                ],
            }),
        ]);
        render(<Turn turn={turn} streaming />);
        expect(screen.getByTestId('ephemeral-status')).toHaveTextContent(
            'Thinking…',
        );
    });

    it('hides the ephemeral entirely when the turn is no longer streaming', () => {
        const turn = _turn([
            _userPrompt('run a thing'),
            _iteration('i1', { content: 'done' }),
        ]);
        render(<Turn turn={turn} />);
        expect(screen.queryByTestId('ephemeral-status')).not.toBeInTheDocument();
    });
});

describe('Turn forwards user_prompt attachments', () => {
    it('renders the optimistic (pending) image preview as a data URL', () => {
        const turn = {
            id: 'turn_0', agentId: 'root.test.1', children: [
                {
                    kind: 'user_prompt', id: 'u1', content: 'look',
                    attachments: [
                        { kind: 'image', src: 'data:image/png;base64,XYZ' },
                    ],
                    isNudge: false,
                },
            ],
        };
        render(<Turn turn={turn} />);
        const img = screen.getByTestId('message-user').querySelector(
            "img[src^='data:image/']",
        );
        expect(img?.getAttribute('src')).toBe('data:image/png;base64,XYZ');
    });

    it('renders the persisted SSE image attachment using its path', () => {
        // After SSE confirmation the FE converts the stored path to a URL.
        // ``container_file_handler`` serves /home/computron/* so the
        // browser can load it as a normal URL.
        const turn = {
            id: 'turn_0', agentId: 'root.test.1', children: [
                {
                    kind: 'user_prompt', id: 'u1', content: 'look',
                    attachments: [
                        { filename: 'red #1.png', content_type: 'image/png',
                          path: '/home/computron/uploads/red #1.png' },
                    ],
                    isNudge: false,
                },
            ],
        };
        render(<Turn turn={turn} />);
        const img = screen.getByTestId('message-user').querySelector('img');
        expect(img?.getAttribute('src')).toBe('/home/computron/uploads/red%20%231.png');
    });

    it('renders a file chip for non-image attachments without dropping them', () => {
        // Persisted shape: {filename, content_type, path} from SSE.
        const turn = {
            id: 'turn_0', agentId: 'root.test.1', children: [
                {
                    kind: 'user_prompt', id: 'u1', content: 'read this',
                    attachments: [
                        { filename: 'notes.txt', content_type: 'text/plain',
                          path: '/u/notes.txt' },
                    ],
                    isNudge: false,
                },
            ],
        };
        render(<Turn turn={turn} />);
        const user = screen.getByTestId('message-user');
        expect(user.textContent).toContain('notes.txt');
    });
});

describe('Turn with nudges interleaved between iterations', () => {
    const _t = (children) => ({ id: 'turn_0', agentId: 'root.test.1', children });

    it('renders a nudge user_prompt between two assistant sections', () => {
        // Sequence: initial user prompt → iteration A → nudge user_prompt → iteration B.
        const turn = _t([
            { kind: 'user_prompt', id: 'u1', content: 'do the thing', attachments: [], isNudge: false },
            { kind: 'iteration', id: 'i1', iterationIndex: 0, content: 'starting…', thinking: '', toolCalls: [] },
            { kind: 'user_prompt', id: 'u2', content: 'also say hi', attachments: [], isNudge: true },
            { kind: 'iteration', id: 'i2', iterationIndex: 1, content: 'hi! continuing…', thinking: '', toolCalls: [] },
        ]);
        render(<Turn turn={turn} />);
        const users = screen.getAllByTestId('message-user');
        const assistants = screen.getAllByTestId('message-assistant');
        expect(users).toHaveLength(2);
        expect(assistants).toHaveLength(2);
        expect(users[0]).toHaveTextContent('do the thing');
        expect(assistants[0]).toHaveTextContent('starting…');
        expect(users[1]).toHaveTextContent('also say hi');
        expect(assistants[1]).toHaveTextContent('hi! continuing…');
    });

    it('keeps thinking from different iterations separate so activity counts are correct', () => {
        // Pre-fix bug: agent.activityLog merged consecutive thinking
        // entries across iteration boundaries → activity summary said
        // "1 thought" even when there were two iterations with thinking.
        // With Turn rendering iterations as ordered entries, each
        // thinking entry is its own item in the merged activity log.
        const turn = _t([
            { kind: 'user_prompt', id: 'u', content: 'go', attachments: [], isNudge: false },
            { kind: 'iteration', id: 'i1', iterationIndex: 0, content: '', thinking: 'first thought', toolCalls: [{ id: 'tc1', name: 'shell', arguments: { cmd: 'echo hi' } }] },
            { kind: 'iteration', id: 'i2', iterationIndex: 1, content: 'done', thinking: 'second thought', toolCalls: [] },
        ]);
        render(<Turn turn={turn} />);
        // Activity summary shows "1 tool · 2 thoughts" when expanded —
        // verified via the toggle's text.
        const toggle = screen.getByTestId('activity-toggle');
        expect(toggle).toHaveTextContent('1 tool');
        expect(toggle).toHaveTextContent('2 thoughts');
    });
});

describe('Turn with mid-turn compaction', () => {
    const _t = (children) => ({ id: 'turn_0', agentId: 'root.test.1', children });

    it('splits the assistant in two when a compaction lands between iterations', () => {
        const turn = _t([
            { kind: 'user_prompt', id: 'u', content: 'go', attachments: [], isNudge: false },
            { kind: 'iteration', id: 'i1', iterationIndex: 0, content: 'pre-compaction work', thinking: '', toolCalls: [] },
            { kind: 'compaction', id: 'c1', summaryText: 'earlier history', userIntentSummary: '', stats: null, timestamp: '2026-01-01T00:00:00' },
            { kind: 'iteration', id: 'i2', iterationIndex: 1, content: 'post-compaction work', thinking: '', toolCalls: [] },
        ]);
        render(<Turn turn={turn} />);
        const assistants = screen.getAllByTestId('message-assistant');
        expect(assistants).toHaveLength(2);
        expect(assistants[0]).toHaveTextContent('pre-compaction work');
        expect(assistants[1]).toHaveTextContent('post-compaction work');
        expect(screen.getByTestId('compaction-chip')).toBeInTheDocument();
        // Chip appears between the two assistant elements (DOM order).
        const allBoxes = screen.getAllByTestId(/message-assistant|compaction-row/);
        expect(allBoxes[0]).toHaveAttribute('data-testid', 'message-assistant');
        expect(allBoxes[1]).toHaveAttribute('data-testid', 'compaction-row');
        expect(allBoxes[2]).toHaveAttribute('data-testid', 'message-assistant');
    });

    it('lands the chip at the start of a turn when keptFromId is the first iteration', () => {
        // Common case: keep_recent_groups=2 with exactly 2 past
        // iterations of the current turn → keptFromId points at the
        // first iteration, projectTurns emits compaction before iter1.
        const turn = _t([
            { kind: 'user_prompt', id: 'u', content: 'go', attachments: [], isNudge: false },
            { kind: 'compaction', id: 'c1', summaryText: 'prior turns summarized', userIntentSummary: '', stats: null, timestamp: '2026-01-01T00:00:00' },
            { kind: 'iteration', id: 'i1', iterationIndex: 0, content: 'response', thinking: '', toolCalls: [] },
        ]);
        render(<Turn turn={turn} />);
        // One assistant element rendered (no split).
        const assistants = screen.getAllByTestId('message-assistant');
        expect(assistants).toHaveLength(1);
        expect(screen.getByTestId('compaction-chip')).toBeInTheDocument();
        // DOM order: user, chip, assistant.
        const items = screen.getAllByTestId(/message-user|compaction-row|message-assistant/);
        expect(items[0]).toHaveAttribute('data-testid', 'message-user');
        expect(items[1]).toHaveAttribute('data-testid', 'compaction-row');
        expect(items[2]).toHaveAttribute('data-testid', 'message-assistant');
    });
});


it('renders a saved goal reply with its question and no model-only metadata', () => {
    const events = [
        { type: 'agent_started', id: 'start', agent_id: 'root.test.1', depth: 0, agent_name: 'Test' },
        { type: 'user_message', id: 'reply', agent_id: 'root.test.1', depth: 0,
            content: 'Saturday at 9 AM', is_nudge: true, context: [{
                type: 'goal_question', goal_id: 'goal_123', question_id: 'start_time',
                question_revision: 1, question: 'When should the cleanup start?', answer: 'Saturday at 9 AM',
            }] },
    ];
    const [turn] = projectTurns(JSON.parse(JSON.stringify(events)));
    render(<Turn turn={turn} />);
    const message = screen.getByTestId('message-user');
    expect(message).toHaveTextContent('↳ When should the cleanup start?');
    expect(message).toHaveTextContent('Saturday at 9 AM');
    expect(message).not.toHaveTextContent('goal_123');
    expect(message).not.toHaveTextContent('start_time');
    expect(message).not.toHaveTextContent('revision');
});


it('pairs each saved question with its full answer, including multiple paragraphs', () => {
    const context = [
        { type: 'goal_question', goal_id: 'g1', question_id: 'service', question_revision: 1,
            question: 'Which service should I purchase?', answer: 'Keep writing it ourselves.\n\nI need to approve it.' },
        { type: 'goal_question', goal_id: 'g1', question_id: 'timing', question_revision: 1,
            question: 'When should I send the notes?', answer: 'Hold all five until the resume is ready.' },
    ];
    const [turn] = projectTurns(JSON.parse(JSON.stringify([
        { type: 'agent_started', id: 'start', agent_id: 'root.test.1', depth: 0, agent_name: 'Test' },
        { type: 'user_message', id: 'reply', agent_id: 'root.test.1', depth: 0,
            content: context.map(item => item.answer).join('\n\n'), context },
    ])));
    render(<Turn turn={turn} />);
    const pairs = screen.getAllByTestId('goal-question-answer');
    expect(pairs).toHaveLength(2);
    expect(pairs[0]).toHaveTextContent(/Which service should I purchase\?\s*Keep writing it ourselves\.\s*I need to approve it\./);
    expect(pairs[0]).not.toHaveTextContent('Hold all five');
    expect(pairs[1]).toHaveTextContent('When should I send the notes?Hold all five until the resume is ready.');
    expect(screen.getAllByText('I need to approve it.')).toHaveLength(1);
    expect(screen.getAllByText('Hold all five until the resume is ready.')).toHaveLength(1);
});

it('keeps model-only goal refresh notices out of the transcript', () => {
    const [turn] = projectTurns([
        { type: 'agent_started', id: 'start', agent_id: 'root.test.1', depth: 0, agent_name: 'Test' },
        { type: 'user_message', id: 'user', agent_id: 'root.test.1', depth: 0, content: 'Continue' },
        { type: 'goal', id: 'notice', agent_id: 'root.test.1', depth: 0,
            goal_id: 'private-goal', data: { kind: 'state_notice', revision: 12, reason: 'state_changed' } },
        { type: 'iteration', id: 'reply', agent_id: 'root.test.1', depth: 0, content: 'Working on it.' },
    ]);
    render(<Turn turn={turn} />);
    expect(screen.getByTestId('message-user')).toHaveTextContent('Continue');
    expect(screen.getByTestId('message-assistant')).toHaveTextContent('Working on it.');
    expect(screen.queryByText(/state_changed|private-goal|read_goal/)).not.toBeInTheDocument();
});

it('renders goal transitions in chronological order outside messages, including before the first turn', () => {
    const milestone = (id, transition, extra = {}) => ({
        type: 'goal', id, goal_id: 'g1', timestamp: '2026-10-23T14:00:00Z',
        data: { kind: transition, objective: 'Keep our community calendar current', resume_at: null, question_count: 0, ...extra },
    });
    const started = (n) => ({ type: 'agent_started', id: `start${n}`, agent_id: `root.test.${n}`, depth: 0 });
    const finished = (n) => ({ type: 'agent_completed', id: `done${n}`, agent_id: `root.test.${n}`, depth: 0, status: 'success' });
    const events = [
        milestone('created', 'started'),
        started(1),
        { type: 'iteration', id: 'work', agent_id: 'root.test.1', depth: 0, content: 'Calendar checked.' },
        milestone('scheduled', 'scheduled', { resume_at: '2026-10-24T14:00:00Z' }),
        finished(1),
        milestone('paused', 'paused'),
        milestone('resumed', 'resumed'),
        started(2),
        { type: 'goal', id: 'returned', goal_id: 'g1', timestamp: '2026-10-23T14:00:00Z',
            data: { kind: 'wakeup', wake_id: 'w1', reason: 'planned', step: 'Check the parks calendar' } },
        milestone('input', 'waiting', { question_count: 3 }),
        finished(2),
        milestone('failed', 'error'),
        started(3),
        milestone('completed', 'completed'),
        finished(3),
        milestone('reopened', 'reopened'),
        milestone('cancelled', 'cancelled'),
    ];
    render(<>{projectTurns(events).map(turn => <Turn key={turn.id} turn={turn} />)}</>);
    const dividers = screen.getAllByTestId('goal-transition');
    expect(dividers.map((divider) => divider.dataset.transition)).toEqual([
        'started', 'scheduled', 'paused', 'resumed', 'run', 'waiting', 'error', 'completed', 'reopened', 'cancelled',
    ]);
    expect(dividers[0]).toHaveTextContent('Goal started· Keep our community calendar current');
    expect(dividers[1]).toHaveTextContent(`Resumes ${formatRunTime('2026-10-24T14:00:00Z')}`);
    expect(dividers[2]).toHaveTextContent('Paused');
    expect(dividers[3]).toHaveTextContent('Resumed');
    expect(dividers[4]).toHaveTextContent('Goal run· Check the parks calendar');
    expect(dividers[5]).toHaveTextContent('Waiting for you· 3 questions');
    expect(dividers[6]).toHaveTextContent('Stopped by an error');
    expect(dividers[6]).not.toHaveTextContent('Waiting');
    expect(dividers[7]).toHaveTextContent('Goal done');
    expect(dividers[8]).toHaveTextContent('Goal reopened');
    expect(dividers[9]).toHaveTextContent('Goal cancelled');
    expect(screen.getAllByTestId('day-header')).toHaveLength(1);
    expect(screen.getAllByTestId('message-assistant')).toHaveLength(1);
    expect(screen.queryByTestId('message-user')).not.toBeInTheDocument();
    expect(dividers[0].compareDocumentPosition(screen.getByText('Calendar checked.')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText('Calendar checked.').compareDocumentPosition(dividers[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
