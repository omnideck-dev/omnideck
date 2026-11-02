import { describe, expect, it } from 'vitest';
import { aggregateUsage } from '../conversationUsage.js';
import { buildConversationDetails } from '../conversationDetailsModel.js';

const report = { prompt_tokens: 100, completion_tokens: 20, cache_read_tokens: 60, cache_creation_tokens: 10, reported_cost_usd: 0.02 };
const agent = (calls) => ({ usageByIteration: Object.fromEntries(calls.map((call, i) => [i, call])) });

describe('per-call usage aggregation', () => {
    it('counts input and output once; cached and cache-write tokens are input subsets', () => {
        const result = aggregateUsage([agent([report, report])]);
        expect(result.total).toEqual({ value: 240, reportedCalls: 2, callCount: 2 });
        expect(result.input.value).toBe(200);
        expect(result.output.value).toBe(40);
        expect(result.cached.value).toBe(120);
        expect(result.cost.value).toBe(0.04);
    });
    it('tracks completeness separately for each metric', () => {
        const result = aggregateUsage([agent([report, { prompt_tokens: 50, completion_tokens: 10 }, null])]);
        expect(result.total).toEqual({ value: 180, reportedCalls: 2, callCount: 3 });
        expect(result.cached).toEqual({ value: 60, reportedCalls: 1, callCount: 3 });
        expect(result.cost).toEqual({ value: 0.02, reportedCalls: 1, callCount: 3 });
    });
    it('preserves legacy totals without fabricating a breakdown', () => {
        const result = aggregateUsage([agent([120, report])]);
        expect(result.total.reportedCalls).toBe(2);
        expect(result.total.value).toBe(240);
        expect(result.input.reportedCalls).toBe(1);
        expect(result.cost.reportedCalls).toBe(1);
    });
    it('keeps real zeros and unavailable values distinct', () => {
        const result = aggregateUsage([agent([{ prompt_tokens: 0, completion_tokens: 0, cache_read_tokens: 0, reported_cost_usd: 0 }])]);
        for (const metric of Object.values(result)) expect(metric).toEqual({ value: 0, reportedCalls: 1, callCount: 1 });
        for (const metric of Object.values(aggregateUsage([]))) expect(metric.value).toBeNull();
        expect(aggregateUsage([agent([{}])]).total.value).toBeNull();
    });
    it('aggregates root spans across turns and descendants without double counting', () => {
        const result = buildConversationDetails({ rootId: 'r2', agents: {
            r1: { ...agent([report]), id: 'r1', parentId: null },
            r2: { ...agent([report]), id: 'r2', parentId: null },
            child: { ...agent([report]), id: 'child', name: 'analyst', parentId: 'r1' },
            grandchild: { ...agent([report]), id: 'grandchild', name: 'reviewer', parentId: 'child' },
        } });
        expect(result.usage.total.value).toBe(480);
        expect(result.agentUsage.map((item) => item.usage.total.value)).toEqual([240, 120, 120]);
        expect(result.usage.cost.value).toBe(0.08);
    });
});
