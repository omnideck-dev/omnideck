import { describe, expect, it } from 'vitest';
import { buildConversationDetails } from '../conversationDetailsModel.js';

const root = { id: 'r', name: 'Primary', parentId: null, usageByIteration: { 0: 120, 1: 80 } };
const child = { id: 'c', name: 'analyst', parentId: 'r', status: 'success', usageByIteration: { 0: 40 } };
const input = { conversationId: 'conv', rootId: 'r', agents: { r: root, c: child } };
const browserId = 'workspace-resource:conv:root:browser';

describe('conversation details projection', () => {
    it('keeps an available resource discoverable after closing its Desktop view', () => {
        const workspace = { r: { browserTabs: { 1: { screenshot: 'png' } }, terminalLines: [{ cmd: 'true', stdout: null }] } };
        const open = buildConversationDetails({ ...input, workspace, openViewsById: { [browserId]: {} } });
        expect(open.rows.find((row) => row.id === browserId).description).toBe('Open in workspace');
        const closed = buildConversationDetails({ ...input, workspace });
        expect(closed.rows.find((row) => row.id === browserId)).toMatchObject({ description: 'View closed', agentId: 'r', resourceId: 'browser' });
        expect(closed.rows.find((row) => row.resourceId === 'terminal')).toBeTruthy();
        expect(closed.updateIds).toEqual(open.updateIds);
    });

    it('omits unused resources and retains only the current root plus sub-agent resources', () => {
        const result = buildConversationDetails({ ...input, agents: { ...input.agents, old: { ...root, id: 'old' } }, workspace: {
            old: { terminalLines: [{ cmd: 'old' }] }, c: { terminalLines: [{ cmd: 'child' }] },
        } });
        expect(result.rows.filter((row) => row.resourceId)).toMatchObject([{ label: 'Analyst · Terminal', agentId: 'c' }]);
        expect(result.rows.find((row) => row.id === 'agents').count).toBe(1);
    });

    it('aggregates primary spans across turns and keeps sub-agent tokens separate', () => {
        const result = buildConversationDetails({ ...input, agents: { ...input.agents, old: { ...root, id: 'old', usageByIteration: { 0: 10 } } } });
        expect(result.totalTokens).toBe(250);
        expect(result.agentUsage.map((agent) => agent.tokens)).toEqual([210, 40]);
    });

    it('does not substitute context occupancy or partial totals for missing usage', () => {
        const result = buildConversationDetails({ ...input, agents: { r: { ...root, usageByIteration: { 0: 120, 1: null }, contextUsage: { context_used: 999 } }, c: child } });
        expect(result.totalTokens).toBeNull();
        expect(result.agentUsage[0].tokens).toBeNull();
        expect(result.agentUsage[1].tokens).toBe(40);
    });

    it('deduplicates artifacts shared by root and sub-agent output', () => {
        const result = buildConversationDetails({ ...input, turns: [{ children: [{ kind: 'file_output', path: '/report.docx' }] }], agents: {
            r: root, c: { ...child, activityLog: [{ type: 'file_output', path: '/report.docx' }] },
        } });
        expect(result.rows[0].updateIds).toEqual(['artifact:/report.docx']);
    });
});
