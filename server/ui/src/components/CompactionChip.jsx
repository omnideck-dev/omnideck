import { useState } from 'react';
import styles from './CompactionChip.module.css';

/** Format a token count as compact (e.g. 12,400 → "12.4k"). */
function _formatTokens(n) {
    if (n == null) return '—';
    if (n < 1000) return String(n);
    return `${(n / 1000).toFixed(1)}k`;
}

/** Format a duration in seconds as "8.8s" / "1m 12s". */
function _formatSeconds(s) {
    if (s == null) return '—';
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    const r = Math.round(s % 60);
    return `${m}m ${r}s`;
}

/** Format an ISO timestamp as a short clock + day label. */
function _formatWhen(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        const today = new Date();
        const isToday = d.toDateString() === today.toDateString();
        const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
        return isToday ? `${time} today` : `${d.toLocaleDateString()} ${time}`;
    } catch {
        return iso;
    }
}

/** Pluralise a count: "3 turns" vs "1 turn". */
function _pl(n, single, plural) {
    return `${n} ${n === 1 ? single : (plural || single + 's')}`;
}

/**
 * Inline divider + chip marking a compaction event. Expands to a card
 * with stats and the two summary sections.
 */
export default function CompactionChip({
    summaryText,
    userIntentSummary,
    stats,
    timestamp,
}) {
    const [open, setOpen] = useState(false);
    const chipLabel = 'earlier conversation compacted';
    // Only surface savings when the next iteration actually shrunk the
    // context. In edge cases (compaction fires mid-turn and the next
    // iteration immediately balloons with new tool output) the "after"
    // measurement is larger than "before" — showing that is misleading,
    // so hide the line.
    const savings = (stats?.saved_tokens != null && stats?.saved_ratio != null && stats.saved_tokens > 0)
        ? `saved ${_formatTokens(stats.saved_tokens)} (${Math.round(stats.saved_ratio * 100)}%)`
        : null;

    return (
        <details
            className={styles.row}
            open={open}
            onToggle={(e) => setOpen(e.target.open)}
            data-testid="compaction-row"
        >
            <summary className={styles.summary} data-testid="compaction-chip">
                <span className={styles.chip}>
                    {chipLabel}
                    <span className={styles.chev}>▸</span>
                </span>
            </summary>
            <div className={styles.panel} data-testid="compaction-panel">
                <p className={styles.intro}>
                    Earlier parts of this conversation were summarized to save room. The agent is now working from the summary, not the originals.
                </p>
                <dl className={styles.stats}>
                    <dt>when</dt>
                    <dd><strong>{_formatWhen(stats?.when ?? timestamp)}</strong></dd>

                    {(stats?.context_before != null || stats?.context_after != null) && (
                        <>
                            <dt>context</dt>
                            <dd>
                                <strong>{_formatTokens(stats?.context_before)}</strong>
                                <span className={styles.arrow}>→</span>
                                <strong>{_formatTokens(stats?.context_after)}</strong>
                                {' tokens'}
                                {savings && <>{' '}<span className={styles.savings}>{savings}</span></>}
                            </dd>
                        </>
                    )}

                    {stats?.spanned_seconds != null && (
                        <>
                            <dt>spanned</dt>
                            <dd>
                                <strong>{_formatSeconds(stats.spanned_seconds)}</strong>
                                {' of conversation'}
                                {stats?.sub_agents_spawned > 0 && (
                                    <> · {_pl(stats.sub_agents_spawned, 'sub-agent')}</>
                                )}
                            </dd>
                        </>
                    )}

                    {stats?.scope && (
                        <>
                            <dt>scope</dt>
                            <dd>
                                <strong>
                                    {_pl(
                                        (stats.scope.user_messages ?? 0)
                                            + (stats.scope.iterations ?? 0),
                                        'message',
                                    )}
                                </strong>
                                {' · '}
                                {_pl(stats.scope.tool_results ?? 0, 'tool call')}
                            </dd>
                        </>
                    )}

                    {stats?.summary_tokens != null && (
                        <>
                            <dt>summary</dt>
                            <dd>
                                <strong>{_formatTokens(stats.summary_tokens)}</strong>
                                {' tokens'}
                            </dd>
                        </>
                    )}

                    {(stats?.elapsed_seconds != null || stats?.model) && (
                        <>
                            <dt>took</dt>
                            <dd>
                                <strong>{_formatSeconds(stats?.elapsed_seconds)}</strong>
                                {stats?.model && <> via <code>{stats.model}</code></>}
                            </dd>
                        </>
                    )}
                </dl>

                {userIntentSummary && (
                    <>
                        <div className={styles.blockLabel}>What the agent thinks you are working on</div>
                        <p className={styles.blockHelp}>
                            A summary of all of your input to the conversation so far.
                        </p>
                        <pre className={styles.blockContent}>{userIntentSummary}</pre>
                    </>
                )}

                {summaryText && (
                    <>
                        <div className={styles.blockLabel}>What the agent thinks it has done</div>
                        <p className={styles.blockHelp}>
                            A summary of all of the work the agent has done so far.
                        </p>
                        <pre className={styles.blockContent}>{summaryText}</pre>
                    </>
                )}
            </div>
        </details>
    );
}
