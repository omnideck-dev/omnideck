import { describe, expect, it } from 'vitest';
import { projectTurns } from '../projectTurns.js';

const _agentStarted = (turnN) => ({
    id: `evt_start_${turnN}`,
    type: 'agent_started',
    agent_id: `root.test.${turnN}`,
    parent_agent_id: null,
});
const _subAgentStarted = (subN, parent) => ({
    id: `evt_substart_${subN}`,
    type: 'agent_started',
    agent_id: `${parent}.sub.${subN}`,
    parent_agent_id: parent,
});
const _userMsg = (content, opts = {}) => ({
    id: opts.id || 'evt_um',
    type: 'user_message',
    content,
    attachments: opts.attachments || [],
    is_nudge: !!opts.isNudge,
});
const _iter = (id, opts = {}) => ({
    id,
    type: 'iteration',
    iteration_index: opts.idx ?? 0,
    content: opts.content || '',
    thinking: opts.thinking || '',
    tool_calls: opts.toolCalls || [],
});
const _toolResult = (id, callId, opts = {}) => ({
    id,
    type: 'tool_result',
    tool_call_id: callId,
    tool_name: opts.name || 'shell',
    content: opts.content || 'ok',
});
const _compaction = (id, keptFromId, opts = {}) => ({
    id,
    type: 'compaction',
    summary_text: opts.summary || 'sum',
    user_intent_summary: opts.intent || '',
    stats: opts.stats || null,
    timestamp: '2026-01-01T00:00:30',
    kept_from_id: keptFromId,
});
const _fileOutput = (id, filename) => ({
    id,
    type: 'file_output',
    filename,
    content_type: 'text/plain',
    path: `/home/computron/${filename}`,
    timestamp: '2026-01-01T00:00:00',
});

describe('projectTurns', () => {
    it('returns [] for empty / missing input', () => {
        expect(projectTurns([])).toEqual([]);
        expect(projectTurns(null)).toEqual([]);
        expect(projectTurns(undefined)).toEqual([]);
    });

    it('groups one turn from agent_started → user → iteration', () => {
        const events = [
            _agentStarted(1),
            _userMsg('hi'),
            _iter('iter1', { content: 'hello back', idx: 0 }),
        ];
        const turns = projectTurns(events);
        expect(turns).toHaveLength(1);
        expect(turns[0].agentId).toBe('root.test.1');
        expect(turns[0].children.map((c) => c.kind)).toEqual([
            'user_prompt', 'iteration',
        ]);
        expect(turns[0].children[0].content).toBe('hi');
        expect(turns[0].children[1].content).toBe('hello back');
    });

    it('starts a new turn at each root agent_started event', () => {
        const events = [
            _agentStarted(1), _userMsg('u1', { id: 'um1' }), _iter('iter_t1'),
            _agentStarted(2), _userMsg('u2', { id: 'um2' }), _iter('iter_t2'),
        ];
        const turns = projectTurns(events);
        expect(turns).toHaveLength(2);
        expect(turns[0].children[0].content).toBe('u1');
        expect(turns[1].children[0].content).toBe('u2');
    });

    it('drops sub-agent (depth>0) events so the sub-agent instruction does not bleed into the chat', () => {
        // Regression: spawn_agent publishes a UserMessagePayload for
        // the sub-agent at depth=1; the projection used to add it to the
        // root turn, surfacing the instruction prompt as a phantom
        // user bubble in the main chat.
        const events = [
            _agentStarted(1),
            _userMsg('please delegate'),
            _iter('root_iter1', { content: 'spawning' }),
            { id: 'sub_started', type: 'agent_started',
              agent_id: 'root.test.1.research.1',
              parent_agent_id: 'root.test.1', depth: 1 },
            { id: 'sub_um', type: 'user_message',
              content: 'Your task: compute 2+2', attachments: [],
              agent_id: 'root.test.1.research.1', depth: 1 },
            { id: 'sub_iter', type: 'iteration', iteration_index: 0,
              content: '4', thinking: null, tool_calls: [],
              agent_id: 'root.test.1.research.1', depth: 1 },
            _iter('root_iter2', { content: 'the answer is 4' }),
        ];
        const turns = projectTurns(events);
        expect(turns).toHaveLength(1);
        expect(turns[0].children.map((c) => c.kind)).toEqual([
            'user_prompt', 'iteration', 'iteration',
        ]);
        // Only the root user prompt remains; the sub-agent instruction
        // is gone from the chat.
        const userPrompts = turns[0].children.filter((c) => c.kind === 'user_prompt');
        expect(userPrompts.map((c) => c.content)).toEqual(['please delegate']);
    });

    it('ignores sub-agent agent_started events', () => {
        const events = [
            _agentStarted(1), _userMsg('u1'),
            _subAgentStarted(1, 'root.test.1'),
            _iter('iter1'),
        ];
        const turns = projectTurns(events);
        expect(turns).toHaveLength(1);
        expect(turns[0].children.map((c) => c.kind))
            .toEqual(['user_prompt', 'iteration']);
    });

    it('flags is_nudge on user_prompt children', () => {
        const events = [
            _agentStarted(1),
            _userMsg('first', { id: 'um1' }),
            _iter('iter1'),
            _userMsg('extra', { id: 'um2', isNudge: true }),
            _iter('iter2'),
        ];
        const turns = projectTurns(events);
        const kinds = turns[0].children.map((c) => `${c.kind}${c.isNudge ? '*' : ''}`);
        expect(kinds).toEqual([
            'user_prompt', 'iteration', 'user_prompt*', 'iteration',
        ]);
    });

    it('places a compaction child right before the iteration referenced by keptFromId', () => {
        // Log order: iter1, iter2, tool_result, compaction (kept_from_id=iter1).
        // Expected children order: chip moves to right before iter1.
        const events = [
            _agentStarted(1),
            _userMsg('u'),
            _iter('iter1', { idx: 0 }),
            _iter('iter2', { idx: 1, toolCalls: [{ id: 'tc1', name: 'shell' }] }),
            _toolResult('tr1', 'tc1'),
            _compaction('c1', 'iter1'),
            _iter('iter3', { idx: 2, content: 'final' }),
        ];
        const turns = projectTurns(events);
        const kinds = turns[0].children.map((c) => c.kind);
        expect(kinds).toEqual([
            'user_prompt', 'compaction',
            'iteration', 'iteration', 'tool_result', 'iteration',
        ]);
        const compIdx = kinds.indexOf('compaction');
        const firstIterIdx = kinds.indexOf('iteration');
        expect(compIdx).toBeLessThan(firstIterIdx);
    });

    it('places a compaction before a mid-turn iteration when keptFromId is mid-turn', () => {
        // 3 past iterations; compaction kept_from_id = iter2 → chip
        // splits the turn between iter1 and iter2.
        const events = [
            _agentStarted(1),
            _userMsg('u'),
            _iter('iter1'),
            _iter('iter2'),
            _iter('iter3'),
            _compaction('c1', 'iter2'),
            _iter('iter4'),
        ];
        const turns = projectTurns(events);
        const kinds = turns[0].children.map((c) => c.kind);
        const ids = turns[0].children.map((c) => c.id);
        expect(kinds).toEqual([
            'user_prompt',
            'iteration', // iter1
            'compaction', // chip
            'iteration', // iter2
            'iteration', // iter3
            'iteration', // iter4
        ]);
        expect(ids[1]).toBe('iter1');
        expect(ids[2]).toBe('c1');
        expect(ids[3]).toBe('iter2');
    });

    it('leaves the compaction where it is when keptFromId is not in the events', () => {
        const events = [
            _agentStarted(1),
            _userMsg('u'),
            _iter('iter1'),
            _compaction('c1', 'evt_missing'),
        ];
        const turns = projectTurns(events);
        const kinds = turns[0].children.map((c) => c.kind);
        expect(kinds).toEqual(['user_prompt', 'iteration', 'compaction']);
    });

    it('passes spawn_requested through as a child so chat can render the spawn card', () => {
        // Regression: the Turn refactor briefly skipped spawn_requested
        // events, which left the chat without spawn cards even though
        // every other code path still emitted them.
        const events = [
            _agentStarted(1),
            _userMsg('delegate this'),
            {
                id: 'sr1', type: 'spawn_requested',
                correlation_id: 'corr-1',
            },
            _iter('iter1', { content: 'done' }),
        ];
        const turns = projectTurns(events);
        const kinds = turns[0].children.map((c) => c.kind);
        expect(kinds).toEqual([
            'user_prompt', 'spawn_requested', 'iteration',
        ]);
        const sr = turns[0].children.find((c) => c.kind === 'spawn_requested');
        expect(sr.correlationId).toBe('corr-1');
    });

    it('passes file_output through as a child', () => {
        const events = [
            _agentStarted(1),
            _userMsg('make a file'),
            _iter('iter1', { content: 'done', toolCalls: [{ id: 'tc1', name: 'write_file' }] }),
            _fileOutput('fo1', 'a.txt'),
        ];
        const turns = projectTurns(events);
        const kinds = turns[0].children.map((c) => c.kind);
        expect(kinds).toEqual(['user_prompt', 'iteration', 'file_output']);
        const fo = turns[0].children.find((c) => c.kind === 'file_output');
        expect(fo.filename).toBe('a.txt');
    });
});


describe('projectTurns with inflight iteration appended (live streaming)', () => {
    // Simulates the session's turns model: when the stream is
    // mid-iteration, it appends a synthetic iteration event built from
    // the inflightIteration state before calling projectTurns. The chat
    // view then shows the streaming content in the current turn's
    // assistant element.
    const _agentStarted = (turnN) => ({
        id: `evt_start_${turnN}`, type: 'agent_started',
        agent_id: `root.test.${turnN}`, parent_agent_id: null,
    });
    const _userMsg = (content) => ({
        id: 'um', type: 'user_message', content, attachments: [],
    });

    it('renders streaming content as an iteration child of the current turn', () => {
        const events = [_agentStarted(1), _userMsg('go')];
        const inflightIteration = {
            agentId: 'root.test.1',
            content: 'partial response…',
            thinking: 'thinking aloud…',
            toolCalls: [],
        };
        const augmented = [...events, {
            id: `_inflight_${inflightIteration.agentId}`,
            type: 'iteration',
            agent_id: inflightIteration.agentId,
            content: inflightIteration.content,
            thinking: inflightIteration.thinking,
            tool_calls: inflightIteration.toolCalls,
        }];
        const turns = projectTurns(augmented);
        expect(turns).toHaveLength(1);
        expect(turns[0].children.map((c) => c.kind)).toEqual([
            'user_prompt', 'iteration',
        ]);
        const iter = turns[0].children[1];
        expect(iter.content).toBe('partial response…');
        expect(iter.thinking).toBe('thinking aloud…');
    });

    it('appends tool_calls captured during streaming to the inflight iteration', () => {
        const events = [_agentStarted(1), _userMsg('do something')];
        const inflight = {
            agentId: 'root.test.1',
            content: '',
            thinking: '',
            toolCalls: [
                { id: 'tc1', name: 'shell', arguments: { cmd: 'ls' } },
            ],
        };
        const augmented = [...events, {
            id: '_inflight', type: 'iteration', agent_id: inflight.agentId,
            content: inflight.content, thinking: inflight.thinking,
            tool_calls: inflight.toolCalls,
        }];
        const turns = projectTurns(augmented);
        const iter = turns[0].children.find((c) => c.kind === 'iteration');
        expect(iter.toolCalls).toHaveLength(1);
        expect(iter.toolCalls[0].name).toBe('shell');
    });

    it('adds a root error event as an error child', () => {
        const turns = projectTurns([
            _agentStarted(1),
            _userMsg('do it'),
            { id: 'evt_err', type: 'error', message: 'usage limit reached', retryable: false },
        ]);
        const err = turns[0].children.find((c) => c.kind === 'error');
        expect(err).toBeTruthy();
        expect(err.message).toBe('usage limit reached');
    });

    it('excludes a sub-agent error from the main chat (depth > 0)', () => {
        const turns = projectTurns([
            _agentStarted(1),
            _userMsg('do it'),
            { id: 'evt_serr', type: 'error', message: 'sub failed', depth: 1, agent_id: 'root.test.1.sub.1' },
        ]);
        expect(turns[0].children.some((c) => c.kind === 'error')).toBe(false);
    });

    it('synthesizes a turn for a root error with no agent_started (setup failure)', () => {
        const turns = projectTurns([
            { id: 'evt_orphan', type: 'error', message: 'setup exploded', depth: 0 },
        ]);
        expect(turns).toHaveLength(1);
        const err = turns[0].children.find((c) => c.kind === 'error');
        expect(err.message).toBe('setup exploded');
    });

    it('renders a truncated (stopped) iteration like any other — partial content shows', () => {
        const turns = projectTurns([
            _agentStarted(1),
            _userMsg('go'),
            { id: 'it1', type: 'iteration', iteration_index: 0, content: 'partial', thinking: '', tool_calls: [], stopped: true },
        ]);
        const iter = turns[0].children.find((c) => c.kind === 'iteration');
        expect(iter.content).toBe('partial');
    });
});

describe('projectTurns — goal chats', () => {
    // Local times, so the day boundary does not depend on the machine's zone.
    const at = (day, hour) => new Date(2026, 9, day, hour).toISOString();
    const root = (n, timestamp) => ({ ..._agentStarted(n), depth: 0, timestamp });
    const wakeup = (id, reason, step, timestamp) => ({
        id, type: 'goal', goal_id: 'g1', agent_id: 'root.test.1', depth: 0, timestamp,
        data: { kind: 'wakeup', wake_id: `w-${id}`, reason, step },
    });
    const transition = (id, kind, timestamp, extra = {}) => ({
        id, type: 'goal', goal_id: 'g1', timestamp,
        data: { kind, objective: 'Book the pavilion', resume_at: null, question_count: 0, ...extra },
    });
    const completed = (n) => ({ id: `evt_done_${n}`, type: 'agent_completed', agent_id: `root.test.${n}`, depth: 0, status: 'success' });
    const reply = (id, n) => ({ ..._iter(id, { content: id }), agent_id: `root.test.${n}`, depth: 0 });
    const dividers = (turns) => turns.flatMap((turn) => turn.children).filter((child) => child.kind === 'goal_transition');

    it('gives every wakeup a run divider with its step, whatever started it', () => {
        const turns = projectTurns([
            root(1, at(23, 9)),
            wakeup('planned', 'planned', 'Call the parks office', at(23, 9)),
            root(2, at(23, 10)),
            wakeup('now', 'run_now', 'Call the parks office', at(23, 10)),
            root(3, at(23, 11)),
            wakeup('retry', 'retry', 'Book the pavilion', at(23, 11)),
            root(4, at(23, 12)),
            wakeup('restart', 'interrupted', '', at(23, 12)),
        ]);
        expect(dividers(turns).map((divider) => [divider.transition, divider.step])).toEqual([
            ['run', 'Call the parks office'], ['run', 'Call the parks office'], ['run', 'Book the pavilion'], ['run', ''],
        ]);
    });

    it('keeps state notices out of the transcript', () => {
        const turns = projectTurns([
            root(1, at(23, 9)),
            { id: 'notice', type: 'goal', goal_id: 'g1', timestamp: at(23, 9), data: { kind: 'state_notice', revision: 3, reason: 'state_changed' } },
        ]);
        expect(turns[0].children.filter((child) => child.kind !== 'day_header')).toEqual([]);
    });

    it('adds a day header before the first message or divider of each new day', () => {
        const turns = projectTurns([
            transition('started', 'started', at(23, 9)),
            root(1, at(23, 9)),
            { ..._userMsg('Find a Saturday', { id: 'ask' }), agent_id: 'root.test.1', depth: 0, timestamp: at(23, 9) },
            transition('scheduled', 'scheduled', at(23, 10), { resume_at: at(24, 9) }),
            root(2, at(24, 9)),
            wakeup('next-day', 'planned', 'Call the parks office', at(24, 9)),
            transition('done', 'completed', at(24, 10)),
            completed(2),
        ]);
        const children = turns.flatMap((turn) => turn.children);
        expect(children.map((child) => child.kind === 'day_header' ? `day:${new Date(child.timestamp).getDate()}` : child.id)).toEqual([
            'day:23', 'started', 'ask', 'scheduled', 'day:24', 'next-day', 'done',
        ]);
    });

    it('marks a turn finished when its root agent completes, not when a sub-agent does', () => {
        const turns = projectTurns([
            root(1, at(23, 9)),
            _subAgentStarted(1, 'root.test.1'),
            { id: 'sub_done', type: 'agent_completed', agent_id: 'root.test.1.sub.1', parent_agent_id: 'root.test.1', depth: 1, status: 'success' },
        ]);
        expect(turns[0].finished).toBe(false);
        expect(projectTurns([root(1, at(23, 9)), completed(1)])[0].finished).toBe(true);
    });

    it('shows a new goal as start, the agent\'s reply, then done', () => {
        const events = [
            transition('started', 'started', at(23, 9)),
            root(1, at(23, 9)),
            wakeup('run', 'planned', '', at(23, 9)),
            reply('tools', 1),
            transition('done', 'completed', at(23, 9)),
            reply('reply', 1),
        ];
        const visible = (turns) => turns.flatMap((turn) => turn.children).filter((child) => child.kind !== 'day_header').map((child) => child.id);
        expect(visible(projectTurns(events))).toEqual(['started', 'tools', 'reply']);
        expect(visible(projectTurns([...events, completed(1)]))).toEqual(['started', 'tools', 'reply', 'done']);
    });

    it('adds no day headers to a chat without a goal', () => {
        const turns = projectTurns([
            root(1, at(23, 9)),
            { ..._userMsg('Hello', { id: 'hi' }), agent_id: 'root.test.1', depth: 0, timestamp: at(23, 9) },
            root(2, at(24, 9)),
            { ..._userMsg('Again', { id: 'again' }), agent_id: 'root.test.2', depth: 0, timestamp: at(24, 9) },
        ]);
        expect(turns.flatMap((turn) => turn.children).some((child) => child.kind === 'day_header')).toBe(false);
    });
});
