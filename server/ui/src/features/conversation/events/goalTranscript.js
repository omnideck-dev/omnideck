import { TRANSCRIPT_ITEM_KINDS as ITEM } from './eventTypes.js';

/**
 * Goal display rules for the chat transcript. Each one takes the turns and
 * returns new turns; none changes the events they came from.
 */

/** Dividers that say how a run left the goal. Only the agent or the end of a run makes them. */
const RUN_OUTCOMES = new Set(['completed', 'scheduled', 'waiting']);

/** @typedef {import('./frontendTypes').ConversationTurn} ConversationTurn */
/** @typedef {import('./frontendTypes').TranscriptItem} TranscriptItem */

/** @param {TranscriptItem|null} item @param {string} transition */
function isTransition(item, transition) {
    return item?.kind === ITEM.GOAL_TRANSITION && item.transition === transition;
}

/** @param {TranscriptItem} item */
function isRunOutcome(item) {
    return item.kind === ITEM.GOAL_TRANSITION && RUN_OUTCOMES.has(item.transition);
}

/**
 * Starting a goal starts its first run at once, so a run divider right after
 * the start divider marks the same moment and is hidden.
 *
 * @param {Array<ConversationTurn>} turns
 * @returns {Array<ConversationTurn>}
 */
export function hideRunAfterStart(turns) {
    /** @type {TranscriptItem|null} */
    let previous = null;
    return turns.map((turn) => {
        const children = turn.children.filter((child) => {
            const hidden = isTransition(child, 'run') && isTransition(previous, 'started');
            previous = child;
            return !hidden;
        });
        return { ...turn, children };
    });
}

/**
 * A run shows one outcome divider: its last one, after the run's own items,
 * once the run has finished. The agent often chooses what happens next and
 * then writes its reply, so the divider would otherwise sit above the reply.
 * Dividers from the user's own actions, such as a pause after the run ended,
 * keep their place.
 *
 * @param {Array<ConversationTurn>} turns
 * @returns {Array<ConversationTurn>}
 */
export function placeRunOutcomes(turns) {
    return turns.map((turn, index) => {
        const outcomes = turn.children.filter(isRunOutcome);
        if (outcomes.length === 0) return turn;
        // A turn without its completion event is still finished once a later turn exists.
        if (!turn.finished && index === turns.length - 1) {
            return { ...turn, children: turn.children.filter((child) => !isRunOutcome(child)) };
        }
        const last = outcomes[outcomes.length - 1];
        const lastRunItem = turn.children.reduce((found, child, i) => (child.kind === ITEM.GOAL_TRANSITION ? found : i), -1);
        // After the run's last own item, or where it happened when nothing of the run came later.
        const position = Math.max(turn.children.indexOf(last), lastRunItem);
        const children = turn.children.flatMap((child, i) => {
            const kept = isRunOutcome(child) ? [] : [child];
            return i === position ? [...kept, last] : kept;
        });
        return { ...turn, children };
    });
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
