import styles from './ConversationDetails.module.css';

function formatCost(value) {
    // Avoid presenting a small, nonzero charge as free.
    if (value > 0 && value < 0.0001) return '<$0.0001';
    return new Intl.NumberFormat('en-US', {
        style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4,
    }).format(value);
}

export function UsageValue({ metric, cost = false }) {
    if (metric.value == null) return <span title="Not reported">—</span>;
    const partial = metric.reportedCalls < metric.callCount;
    return <span title={`${metric.value.toLocaleString('en-US', { maximumFractionDigits: 12 })} ${cost ? 'USD' : 'tokens'} · Reported for ${metric.reportedCalls} of ${metric.callCount} calls`}>
        {cost ? formatCost(metric.value) : metric.value.toLocaleString('en-US')}
        {partial && <small className={styles.partial}> partial</small>}
    </span>;
}

export default function AgentUsageDetails({ agents }) {
    return <section className={styles.usage} aria-label="Usage by agent">
        <h3>Usage by agent</h3>
        {agents.map((agent) => <details key={agent.id} className={styles.agentUsage} open={agent.id === 'primary'}>
            <summary>
                <i className="bi bi-chevron-right" aria-hidden="true" />
                <strong>{agent.label}</strong>
                <span className={styles.agentTotals}>
                    <span><UsageValue metric={agent.usage.total} /> tokens</span>
                    <UsageValue metric={agent.usage.cost} cost />
                </span>
            </summary>
            <dl className={styles.breakdown}>
                <div><dt>Input</dt><dd><UsageValue metric={agent.usage.input} /></dd></div>
                {agent.usage.cached.value != null && <div className={styles.cached}>
                    <dt>Of which cached</dt><dd><UsageValue metric={agent.usage.cached} /></dd>
                </div>}
                <div><dt>Output</dt><dd><UsageValue metric={agent.usage.output} /></dd></div>
                <div><dt>Reported cost</dt><dd><UsageValue metric={agent.usage.cost} cost /></dd></div>
            </dl>
        </details>)}
    </section>;
}
