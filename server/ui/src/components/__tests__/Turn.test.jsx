import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Turn from '../Turn.jsx';

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
        // After SSE confirmation the FE uses the served path directly —
        // ``container_file_handler`` serves /home/computron/* so the
        // browser can load it as a normal URL.
        const turn = {
            id: 'turn_0', agentId: 'root.test.1', children: [
                {
                    kind: 'user_prompt', id: 'u1', content: 'look',
                    attachments: [
                        { filename: 'red.png', content_type: 'image/png',
                          path: '/home/computron/uploads/red.png' },
                    ],
                    isNudge: false,
                },
            ],
        };
        render(<Turn turn={turn} />);
        const img = screen.getByTestId('message-user').querySelector('img');
        expect(img?.getAttribute('src')).toBe('/home/computron/uploads/red.png');
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
        // first iteration, _buildTurns emits compaction before iter1.
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
