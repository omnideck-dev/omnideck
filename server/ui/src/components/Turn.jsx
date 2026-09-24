import React from 'react';
import {
    CONVERSATION_EVENT_TYPES as EVENT,
    TRANSCRIPT_ITEM_KINDS as ITEM,
} from '../features/conversation/events/eventTypes.js';
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
 * Normalize a user_prompt's attachments into the ordered
 * ``{src, filename, content_type}`` shape UserMessage renders, preserving
 * upload order across images and files. Two shapes arrive here:
 *  - optimistic pending: ``{kind: 'image', src}`` (FE base64 data URL so the
 *    thumbnail shows before the round-trip completes) and ``{filename,
 *    content_type}`` for non-image previews.
 *  - persisted SSE/log: ``{filename, content_type, path}``. ``path`` is served
 *    by the container_file_handler route, so it works directly as an
 *    ``<img src>``.
 */
function _normalizeAttachments(attachments) {
    const out = [];
    for (const a of (attachments || [])) {
        if (!a) continue;
        if (a.kind === 'image' && a.src) {
            out.push({ src: a.src, filename: a.filename, content_type: a.content_type });
        } else if (a.path && a.content_type && a.content_type.startsWith('image/')) {
            out.push({ src: a.path, filename: a.filename, content_type: a.content_type });
        } else if (a.filename || a.content_type) {
            out.push({ src: null, filename: a.filename, content_type: a.content_type });
        }
    }
    return out;
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
    stalled = false,
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
        if (child.kind === ITEM.USER_PROMPT) {
            flushAssistant();
            items.push({ kind: 'user', child });
        } else if (child.kind === ITEM.COMPACTION) {
            flushAssistant();
            items.push({ kind: 'compaction', child });
        } else if (child.kind === ITEM.ERROR) {
            flushAssistant();
            items.push({ kind: 'error', child });
        } else if (child.kind === ITEM.ITERATION) {
            if (entries === null) entries = [];
            entries.push(..._iterationToEntries(child));
        } else if (child.kind === ITEM.FILE_OUTPUT) {
            if (entries === null) entries = [];
            entries.push(_fileOutputToEntry(child));
        } else if (child.kind === ITEM.SPAWN_REQUESTED) {
            if (entries === null) entries = [];
            entries.push({
                type: EVENT.SPAWN_REQUESTED,
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

    return (
        <div data-testid="turn" data-turn-id={turn.id}>
            {items.map((item, i) => {
                if (item.kind === 'user') {
                    return (
                        <Message
                            key={`u-${item.child.id}`}
                            role="user"
                            content={item.child.content}
                            attachments={_normalizeAttachments(item.child.attachments)}
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
                        stalled={stalled}
                        onPreview={onPreview}
                        spawnedAgents={spawnedAgents}
                        onSelectAgent={onSelectAgent}
                    />
                );
            })}
        </div>
    );
}
