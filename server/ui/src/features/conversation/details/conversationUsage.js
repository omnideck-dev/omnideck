/** Sum persisted per-call reports only; context occupancy is a different metric. */
export function aggregateUsage(agents) {
    const calls = agents.flatMap((agent) => Object.values(agent.usageByIteration || {}));
    const isCount = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    const metric = (read) => {
        const values = calls.map(read).filter(isCount);
        return {
            value: values.length ? values.reduce((sum, value) => sum + value, 0) : null,
            reportedCalls: values.length,
            callCount: calls.length,
        };
    };
    return {
        input: metric((call) => call?.prompt_tokens),
        output: metric((call) => call?.completion_tokens),
        cached: metric((call) => call?.cache_read_tokens),
        cost: metric((call) => call?.reported_cost_usd),
        total: metric((call) => {
            // Earlier conversation logs only recorded a scalar total. Preserve
            // that value without inventing an input/output/cache breakdown.
            if (isCount(call)) return call;
            if (!isCount(call?.prompt_tokens) || !isCount(call?.completion_tokens)) return null;
            return call.prompt_tokens + call.completion_tokens;
        }),
    };
}
