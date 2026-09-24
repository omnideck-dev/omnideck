import { useState } from 'react';
import styles from './CompactionRow.module.css';
import { formatTokens } from '../utils/agentUtils.js';

/**
 * Compaction marker for the agent activity rail. Collapsed it's a single
 * line; click expands the savings/scope stats and the two summary blocks.
 *
 * This is the per-agent counterpart to the chat's CompactionChip — it
 * surfaces compactions that happen inside a sub-agent, which the main
 * chat (depth>0 filtered) never shows.
 */
export default function CompactionRow({ stats, summaryText, userIntentSummary }) {
    const [open, setOpen] = useState(false);

    const scope = stats?.scope;
    const msgs = scope ? (scope.user_messages ?? 0) + (scope.iterations ?? 0) : null;
    const savings = (stats?.saved_tokens != null && stats?.saved_ratio != null && stats.saved_tokens > 0)
        ? `saved ${formatTokens(stats.saved_tokens)} (${Math.round(stats.saved_ratio * 100)}%)`
        : null;

    return (
        <details
            className={styles.row}
            open={open}
            onToggle={(e) => setOpen(e.target.open)}
            data-testid="activity-compaction"
        >
            <summary className={styles.summary} data-testid="activity-compaction-summary">
                <span className={styles.label}>compacted</span>
                {msgs != null && <span className={styles.meta}>· {msgs} msg{msgs === 1 ? '' : 's'} → summary</span>}
                {savings && <span className={styles.savings}>· {savings}</span>}
                <span className={styles.chev} aria-hidden="true">▸</span>
            </summary>
            <div className={styles.panel} data-testid="activity-compaction-panel">
                <dl className={styles.stats}>
                    {(stats?.context_before != null || stats?.context_after != null) && (
                        <>
                            <dt>context</dt>
                            <dd>
                                {formatTokens(stats?.context_before) ?? '—'}
                                <span className={styles.arrow}>→</span>
                                {formatTokens(stats?.context_after) ?? '—'} tokens
                            </dd>
                        </>
                    )}
                    {scope && (
                        <>
                            <dt>scope</dt>
                            <dd>{msgs} messages · {scope.tool_results ?? 0} tool calls</dd>
                        </>
                    )}
                    {stats?.summary_tokens != null && (
                        <>
                            <dt>summary</dt>
                            <dd>{formatTokens(stats.summary_tokens) ?? '—'} tokens{stats?.model && <> · via <code>{stats.model}</code></>}</dd>
                        </>
                    )}
                </dl>
                {userIntentSummary && (
                    <>
                        <div className={styles.blockLabel}>What the agent thinks you are working on</div>
                        <pre className={styles.blockContent}>{userIntentSummary}</pre>
                    </>
                )}
                {summaryText && (
                    <>
                        <div className={styles.blockLabel}>What the agent thinks it has done</div>
                        <pre className={styles.blockContent}>{summaryText}</pre>
                    </>
                )}
            </div>
        </details>
    );
}
