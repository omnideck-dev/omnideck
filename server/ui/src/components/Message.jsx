import React, { useState } from 'react';
import styles from './Message.module.css';
import MarkdownContent from './MarkdownContent.jsx';
import AgentOutput from './AgentOutput.jsx';
import AttachmentChip from './AttachmentChip.jsx';

// Entry types that remain visible inline in the chat. Thinking and raw
// tool_call entries are hidden — surfaced via the ephemeral status row
// while streaming and the per-turn activity footer afterward.
const _VISIBLE_INLINE = new Set(['content', 'spawn_requested', 'file_output']);

function _isVisibleInline(entry) {
    return _VISIBLE_INLINE.has(entry?.type);
}

function _isHidden(entry) {
    return entry?.type === 'thinking' || entry?.type === 'tool_call';
}

/** Caption for the ephemeral activity row, based on the last entry.
 *
 * Using ``lastEntry`` (rather than matching tool_call ids against
 * tool_result events) makes the indicator immune to React batching:
 * when a tool executes quickly, the iteration event and its tool_result
 * arrive in the same TCP chunk and are processed in the same render.
 * A ``currentTool`` computed from tool_result matching would already be
 * null by then, so "Calling X…" would never render.  ``lastEntry`` is
 * derived from the entries list alone — if the most recent entry is a
 * tool_call, the agent is (or was just) executing tools, and "Calling
 * X…" is the right message regardless of whether the result has landed. */
function _ephemeralText(entry, stalled) {
    // spawn_agent runs the whole sub-agent lifecycle (can be minutes);
    // the SpawnCard owns that visual, so don't say "Calling spawn_agent…".
    if (entry?.type === 'tool_call' && entry.name !== 'spawn_agent') {
        return `Calling ${entry.name || 'tool'}…`;
    }
    // Content is done but the turn is still streaming and has gone quiet —
    // the model is producing something that emits no content tokens (usually
    // a large tool call whose arguments stream silently). "Working…" keeps the
    // indicator honest without claiming it's thinking or naming a tool we
    // don't know yet.
    if (stalled && entry?.type === 'content') return 'Working…';
    return 'Thinking…';
}

/** Build the per-turn summary shown on the activity footer. */
function _summary(hidden) {
    const tools = hidden.filter((e) => e.type === 'tool_call').length;
    const thoughts = hidden.filter((e) => e.type === 'thinking').length;
    if (tools === 0 && thoughts === 0) return '';
    const parts = [];
    if (tools > 0) parts.push(`${tools} tool${tools === 1 ? '' : 's'}`);
    if (thoughts > 0) parts.push(`${thoughts} thought${thoughts === 1 ? '' : 's'}`);
    return parts.join(' · ');
}

/**
 * One assistant message. Thinking and tool-call entries are not rendered
 * inline — while streaming, an ephemeral pulse row at the bottom reflects
 * the agent's current activity; once finished, a faint footer reveals the
 * full chronological activity on click. Content, spawn cards, and file
 * outputs stay inline as they always have.
 *
 * ``stalled`` marks that the stream has gone silent mid-turn (see
 * useStreamStall). When it does, a finished content entry stops counting as
 * "streaming inline" so the ephemeral row reappears — otherwise the bubble
 * would sit frozen with no indicator while the model streams, say, a large
 * tool call that emits no content tokens.
 */
function AssistantMessage({ entries, onPreview, streaming, stalled = false,
                            spawnedAgents, onSelectAgent }) {
    const [activityOpen, setActivityOpen] = useState(false);
    const list = Array.isArray(entries) ? entries : [];
    const hasEntries = list.length > 0;
    const visibleEntries = list.filter(_isVisibleInline);
    const hiddenEntries = list.filter(_isHidden);
    const lastEntry = list[list.length - 1];

    // Stream-animate the inline content when the most recent entry is a
    // visible one (content / spawn_requested / file_output). Otherwise
    // the ephemeral row owns the "what is the agent doing" indicator. A
    // stalled stream drops out of inline streaming so the ephemeral row
    // takes over from the static content.
    const streamInline = streaming && _isVisibleInline(lastEntry) && !stalled;
    const showEphemeral = streaming && !streamInline;
    const summary = _summary(hiddenEntries);

    return (
        <div className={`${styles.message} ${styles.assistant}`} data-testid="message-assistant">
            <div className={styles.bubble}>
                {hasEntries && visibleEntries.length > 0 && (
                    <AgentOutput
                        entries={visibleEntries}
                        streaming={streamInline}
                        onPreview={onPreview}
                        spawnedAgents={spawnedAgents}
                        onSelectAgent={onSelectAgent}
                    />
                )}
                {showEphemeral && (
                    <div className={styles.ephemeral} data-testid="ephemeral-status">
                        <span className={styles.pulse} aria-hidden="true" />
                        <span className={styles.ephemeralText}>{_ephemeralText(lastEntry, stalled)}</span>
                    </div>
                )}
                {!streaming && summary && (
                    <>
                        <div className={`${styles.activityFooter}${activityOpen ? ` ${styles.activityFooterOpen}` : ''}`}>
                            <button
                                type="button"
                                onClick={() => setActivityOpen((v) => !v)}
                                data-testid="activity-toggle"
                                aria-expanded={activityOpen}
                            >
                                <span className={styles.activityChev} aria-hidden="true">▶</span>
                                {activityOpen ? 'Hide' : 'Show'} activity ({summary})
                            </button>
                        </div>
                        {activityOpen && (
                            <div className={styles.activityPanel} data-testid="activity-panel">
                                {hiddenEntries.map((e, i) => (
                                    <div
                                        key={i}
                                        className={`${styles.entry} ${styles[`entry_${e.type}`] || ''}`}
                                        data-testid={`activity-entry-${e.type}`}
                                    >
                                        <span className={styles.marker}>{e.type === 'tool_call' ? 'tool' : 'think'}</span>
                                        <span className={styles.entryBody}>
                                            {e.type === 'tool_call' ? (
                                                <>
                                                    <span className={styles.toolName}>{e.name}</span>
                                                    {e.arguments && Object.keys(e.arguments).length > 0 && (
                                                        <span className={styles.toolArgs}>
                                                            {' '}({Object.entries(e.arguments).map(([k, v]) => `${k}="${v}"`).join(', ')})
                                                        </span>
                                                    )}
                                                </>
                                            ) : (
                                                e.thinking || ''
                                            )}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}

function UserMessage({ content, images, files }) {
    const imageList = Array.isArray(images) ? images : [];
    const fileList = Array.isArray(files) ? files : [];
    const hasAttachments = imageList.length > 0 || fileList.length > 0;
    return (
        <div className={`${styles.message} ${styles.user}`} data-testid="message-user">
            <div className={styles.bubble}>
                {hasAttachments && (
                    <div className={styles.attachments}>
                        {imageList.map((src, i) => (
                            <AttachmentChip key={`img-${i}`} src={src} />
                        ))}
                        {fileList.map((f, i) => (
                            <AttachmentChip key={`file-${i}`} filename={f.filename} />
                        ))}
                    </div>
                )}
                {content && <MarkdownContent>{content}</MarkdownContent>}
            </div>
        </div>
    );
}

export default function Message(props) {
    return props.role === 'assistant' ? (
        <AssistantMessage {...props} />
    ) : (
        <UserMessage {...props} />
    );
}
