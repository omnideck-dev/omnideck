import { describe, expect, it } from 'vitest';
import { _buildTurns } from '../useStreamingChat.js';

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

describe('_buildTurns', () => {
    it('returns [] for empty / missing input', () => {
        expect(_buildTurns([])).toEqual([]);
        expect(_buildTurns(null)).toEqual([]);
        expect(_buildTurns(undefined)).toEqual([]);
    });

    it('groups one turn from agent_started → user → iteration', () => {
        const events = [
            _agentStarted(1),
            _userMsg('hi'),
            _iter('iter1', { content: 'hello back', idx: 0 }),
        ];
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
        expect(turns).toHaveLength(2);
        expect(turns[0].children[0].content).toBe('u1');
        expect(turns[1].children[0].content).toBe('u2');
    });

    it('drops sub-agent (depth>0) events so the sub-agent instruction does not bleed into the chat', () => {
        // Regression: spawn_agent publishes a UserMessagePayload for
        // the sub-agent at depth=1; _buildTurns used to add it to the
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
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
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
        const turns = _buildTurns(events);
        const kinds = turns[0].children.map((c) => c.kind);
        expect(kinds).toEqual(['user_prompt', 'iteration', 'file_output']);
        const fo = turns[0].children.find((c) => c.kind === 'file_output');
        expect(fo.filename).toBe('a.txt');
    });
});


describe('_buildTurns with inflight iteration appended (live streaming)', () => {
    // Simulates what useStreamingChat's turns memo does: when the SSE is
    // mid-iteration, it appends a synthetic iteration event built from
    // the inflightIteration state before calling _buildTurns. The chat
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
        const turns = _buildTurns(augmented);
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
        const turns = _buildTurns(augmented);
        const iter = turns[0].children.find((c) => c.kind === 'iteration');
        expect(iter.toolCalls).toHaveLength(1);
        expect(iter.toolCalls[0].name).toBe('shell');
    });
});
