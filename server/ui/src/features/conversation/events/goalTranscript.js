import { TRANSCRIPT_ITEM_KINDS as ITEM } from './eventTypes.js';

/**
 * Goal display rules for the chat transcript. Each one takes the turns and
 * returns new turns; none changes the events they came from.
 */

/** @typedef {import('./frontendTypes').ConversationTurn} ConversationTurn */
/** @typedef {import('./frontendTypes').TranscriptItem} TranscriptItem */

const SHOWN_GOAL_KINDS = new Set(['wakeup', 'scheduled', 'waiting', 'error', 'completed']);

/**
 * @param {{ data?: { kind?: string } } | null | undefined} event
 * @returns {boolean}
 */
export function isShownGoalEvent(event) {
    return SHOWN_GOAL_KINDS.has(event?.data?.kind || '');
}

/**
 * The transcript divider for a goal event, or null for one the transcript does not show.
 *
 * @param {Extract<import('./conversationEvents.generated').ConversationEvent, { type: 'goal' }>} event
 * @returns {TranscriptItem | null}
 */
export function goalDividerItem(event) {
    if (!isShownGoalEvent(event)) return null;
    const data = event.data;
    if (data.kind === 'wakeup') {
        return {
            kind: ITEM.GOAL_TRANSITION, id: event.id, transition: 'run', step: data.step,
            questionCount: 0, timestamp: event.timestamp, resumeAt: null,
        };
    }
    return {
        kind: ITEM.GOAL_TRANSITION, id: event.id,
        transition: /** @type {'scheduled' | 'waiting' | 'error' | 'completed'} */ (data.kind),
        step: '', questionCount: data.question_count || 0, timestamp: event.timestamp, resumeAt: data.resume_at,
    };
}

/** @param {string} timestamp */
function localDay(timestamp) {
    const date = new Date(timestamp);
    return Number.isNaN(date.getTime()) ? null : date.toDateString();
}

/**
 * Goal chats span days, so a small day header marks each change of day
 * before the first message or goal divider of that day. Chats without a goal
 * get none.
 *
 * @param {Array<ConversationTurn>} turns
 * @returns {Array<ConversationTurn>}
 */
export function addDayHeaders(turns) {
    const hasGoal = turns.some((turn) => turn.children.some((child) => child.kind === ITEM.GOAL_TRANSITION));
    if (!hasGoal) return turns;
    /** @type {string|null} */
    let lastDay = null;
    return turns.map((turn) => {
        /** @type {Array<TranscriptItem>} */
        const children = [];
        for (const child of turn.children) {
            const stamp = child.kind === ITEM.USER_PROMPT || child.kind === ITEM.GOAL_TRANSITION ? child.timestamp : null;
            const day = stamp ? localDay(stamp) : null;
            if (stamp && day && day !== lastDay) {
                children.push({ kind: ITEM.DAY_HEADER, id: `day_${child.id}`, timestamp: stamp });
                lastDay = day;
            }
            children.push(child);
        }
        return { ...turn, children };
    });
}
