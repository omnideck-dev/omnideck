import { describe, expect, it } from 'vitest';
import { isRootAgentEvent, isSubAgentEvent } from '../eventTypes.js';

describe('agent event scope', () => {
    it('does not classify a missing event as root or sub-agent activity', () => {
        expect(isRootAgentEvent(null)).toBe(false);
        expect(isSubAgentEvent(null)).toBe(false);
    });

    it('treats an event without a parent or positive depth as root activity', () => {
        expect(isRootAgentEvent({ type: 'iteration', depth: 0 })).toBe(true);
        expect(isRootAgentEvent({ type: 'agent_started', parent_agent_id: null })).toBe(true);
    });

    it('recognizes a sub-agent lifecycle event from its parent id', () => {
        const event = { type: 'agent_started', parent_agent_id: 'root.test.1' };
        expect(isSubAgentEvent(event)).toBe(true);
        expect(isRootAgentEvent(event)).toBe(false);
    });

    it('recognizes other sub-agent events from their depth', () => {
        const event = { type: 'iteration', depth: 1 };
        expect(isSubAgentEvent(event)).toBe(true);
        expect(isRootAgentEvent(event)).toBe(false);
    });
});
