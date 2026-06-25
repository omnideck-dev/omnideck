import React from 'react';
import Message from './Message.jsx';
import CompactionChip from './CompactionChip.jsx';
import Callout from './primitives/Callout.jsx';
import styles from './Message.module.css';

/**
 * Convert one iteration child from a Turn into the flat `entries` shape
 * the existing AssistantMessage component expects.
 */
function _iterationToEntries(iter) {
    const entries = [];
    if (iter.thinking) {
        entries.push({ type: 'thinking', thinking: iter.thinking });
    }
    if (iter.content) {
        entries.push({ type: 'content', content: iter.content });
    }
    for (const tc of (iter.toolCalls || [])) {
        entries.push({
            type: 'tool_call',
            name: tc.name,
            arguments: tc.arguments,
        });
    }
    return entries;
}

/**
 * Split a user_prompt's attachments list into the {images, files} shape
 * the UserMessage component expects. Two shapes arrive here:
 *  - optimistic pending: ``{kind: 'image', src}`` (FE base64 data URL
 *    so the thumbnail shows before the round-trip completes) and
 *    ``{filename, content_type}`` for non-image previews.
 *  - persisted SSE/log: ``{filename, content_type, path}``. ``path`` is
 *    served by the container_file_handler route, so it works directly
 *    as an ``<img src>``.
 */
function _splitAttachments(attachments) {
    const images = [];
    const files = [];
    for (const a of (attachments || [])) {
        if (!a) continue;
        if (a.kind === 'image' && a.src) {
            images.push(a.src);
        } else if (a.path && a.content_type && a.content_type.startsWith('image/')) {
            images.push(a.path);
        } else if (a.filename) {
            files.push({ filename: a.filename, content_type: a.content_type });
        }
    }
    return { images, files };
}

function _fileOutputToEntry(fo) {
    return {
        type: 'file_output',
        filename: fo.filename,
        content_type: fo.contentType,
        path: fo.path,
        timestamp: fo.timestamp,
    };
}

/**
 * Walk the turn's children and return the tool_call the agent is
 * currently waiting on — the first one from any iteration whose
 * matching tool_result has not yet arrived. ``spawn_agent`` is skipped
 * because its execution is conveyed by the SpawnCard, not the
 * "Calling X…" ephemeral.
 *
 * Returns ``null`` once every tool has its result (model is back to
 * thinking) or when no iteration has tool_calls at all.
 */
function _currentRunningTool(children) {
    const completedIds = new Set();
    const calls = [];
    for (const child of children) {
        if (child.kind === 'iteration') {
            for (const tc of (child.toolCalls || [])) {
                if (tc?.name === 'spawn_agent') continue;
                calls.push(tc);
            }
        } else if (child.kind === 'tool_result') {
            if (child.toolCallId) completedIds.add(child.toolCallId);
        }
    }
    for (const tc of calls) {
        if (!tc.id || !completedIds.has(tc.id)) {
            return { name: tc.name, id: tc.id };
        }
    }
    return null;
}


/**
 * Render one Turn. Walks the turn's children in order, groups
 * consecutive iterations (and any file_outputs between them) into a
 * single assistant Message element to preserve today's visual look,
 * and splits the assistant element whenever a compaction child sits
 * between iterations.
 *
 * Children of kind ``tool_result``, ``terminal_output``, and
 * ``browser_screenshot`` aren't rendered here — they live in the
 * preview panels / activity rail, fed by the agent reducer, and don't
 * affect the chat layout.
 */
export default function Turn({
    turn,
    onPreview,
    spawnedAgents,
    onSelectAgent,
    streaming,
}) {
    if (!turn || !Array.isArray(turn.children)) return null;

    const items = [];
    let entries = null;

    const flushAssistant = () => {
        if (entries && entries.length > 0) {
            items.push({ kind: 'assistant', entries });
        }
        entries = null;
    };

    for (const child of turn.children) {
        if (child.kind === 'user_prompt') {
            flushAssistant();
            items.push({ kind: 'user', child });
        } else if (child.kind === 'compaction') {
            flushAssistant();
            items.push({ kind: 'compaction', child });
        } else if (child.kind === 'error') {
            flushAssistant();
            items.push({ kind: 'error', child });
        } else if (child.kind === 'iteration') {
            if (entries === null) entries = [];
            entries.push(..._iterationToEntries(child));
        } else if (child.kind === 'file_output') {
            if (entries === null) entries = [];
            entries.push(_fileOutputToEntry(child));
        } else if (child.kind === 'spawn_requested') {
            if (entries === null) entries = [];
            entries.push({
                type: 'spawn_requested',
                correlationId: child.correlationId,
            });
        }
        // tool_result, terminal_output, browser_screenshot: handled by
        // other parts of the UI (preview panels, activity rail).
    }
    flushAssistant();

    // While the agent is running but hasn't produced any assistant output
    // yet (the gap between turn start and the first token, including a turn
    // that fails before streaming anything), show an empty streaming
    // assistant so the "Thinking…" row gives feedback during the wait.
    if (streaming && !items.some((it) => it.kind === 'assistant')) {
        items.push({ kind: 'assistant', entries: [] });
    }

    const currentTool = streaming ? _currentRunningTool(turn.children) : null;

    return (
        <div data-testid="turn" data-turn-id={turn.id}>
            {items.map((item, i) => {
                if (item.kind === 'user') {
                    const { images, files } = _splitAttachments(item.child.attachments);
                    return (
                        <Message
                            key={`u-${item.child.id}`}
                            role="user"
                            content={item.child.content}
                            images={images}
                            files={files}
                        />
                    );
                }
                if (item.kind === 'compaction') {
                    return (
                        <CompactionChip
                            key={`c-${item.child.id}`}
                            summaryText={item.child.summaryText}
                            userIntentSummary={item.child.userIntentSummary}
                            stats={item.child.stats}
                            timestamp={item.child.timestamp}
                        />
                    );
                }
                if (item.kind === 'error') {
                    return (
                        <div key={`e-${item.child.id}`} data-testid="turn-error" className={styles.turnError}>
                            <Callout
                                tone="danger"
                                title="Something went wrong"
                                description={item.child.message}
                            />
                        </div>
                    );
                }
                // assistant section
                const isLast = i === items.length - 1;
                return (
                    <Message
                        key={`a-${i}`}
                        role="assistant"
                        entries={item.entries}
                        streaming={!!streaming && isLast}
                        currentTool={isLast ? currentTool : null}
                        onPreview={onPreview}
                        spawnedAgents={spawnedAgents}
                        onSelectAgent={onSelectAgent}
                    />
                );
            })}
        </div>
    );
}
