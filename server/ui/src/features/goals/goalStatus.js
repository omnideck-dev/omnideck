/** One status for a goal everywhere: header, conversation list, details and dividers. */

export function isGoalOpen(goal) {
    return Boolean(goal && !['done', 'cancelled'].includes(goal.next?.kind));
}

/** Open questions the user has not answered yet. */
export function unansweredQuestions(goal) {
    return (goal?.questions || []).filter((q) => q.status === 'open' && q.answers.length <= q.reviewed_answer_count);
}

/** Open questions the goal waits on, for "N questions for you". */
function blockingQuestionCount(goal) {
    if (goal?.next?.kind !== 'wait') return 0;
    const open = new Set(unansweredQuestions(goal).map((q) => q.id));
    return goal.next.question_ids.filter((id) => open.has(id)).length;
}

export function formatRunTime(value) {
    const date = new Date(value);
    return date.toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' });
}

export function plural(count, word) {
    return `${count} ${word}${count === 1 ? '' : 's'}`;
}

const TONES = {
    done: { icon: 'bi-check-circle', tone: 'success' },
    cancelled: { icon: 'bi-x-circle', tone: 'neutral' },
    paused: { icon: 'bi-pause-circle', tone: 'neutral' },
    working: { icon: 'bi-arrow-repeat', tone: 'accent' },
    error: { icon: 'bi-exclamation-triangle', tone: 'danger' },
    questions: { icon: 'bi-chat-left-text', tone: 'warning' },
    waiting: { icon: 'bi-chat-left-text', tone: 'warning' },
    scheduled: { icon: 'bi-clock', tone: 'neutral' },
    starting: { icon: 'bi-play-circle', tone: 'accent' },
};

export function statusTone(key) {
    return TONES[key] || TONES.waiting;
}

/**
 * Derive the status the user sees, checked in the order of the requirements table.
 * Returns { key, label, shortLabel, icon, tone, extraQuestions }.
 */
export function goalStatus(goal, now = Date.now()) {
    if (!goal) return null;
    const next = goal.next || {};
    let key;
    let label;
    let shortLabel;
    if (next.kind === 'done') { key = 'done'; label = 'Done'; }
    else if (next.kind === 'cancelled') { key = 'cancelled'; label = 'Cancelled'; }
    else if (goal.paused) { key = 'paused'; label = 'Paused'; }
    else if (goal.running) { key = 'working'; label = 'Working'; }
    else if (next.kind === 'error') { key = 'error'; label = 'Stopped by an error'; shortLabel = 'Error'; }
    else if (next.kind === 'wait' && blockingQuestionCount(goal) > 0) {
        const count = blockingQuestionCount(goal);
        key = 'questions';
        label = `${plural(count, 'question')} for you`;
        shortLabel = plural(count, 'question');
    } else if (next.kind === 'wait') { key = 'waiting'; label = 'Waiting for you'; shortLabel = 'Waiting'; }
    else if (next.kind === 'wake' && Date.parse(next.at) > now) {
        key = 'scheduled';
        label = `Resumes ${formatRunTime(next.at)}`;
        shortLabel = formatRunTime(next.at);
    } else { key = 'starting'; label = 'Starting'; }
    // Open questions that do not block work add a count; they never change the status.
    const extraQuestions = ['done', 'cancelled', 'questions'].includes(key) ? 0 : unansweredQuestions(goal).length;
    if (extraQuestions) {
        label = `${label} · ${plural(extraQuestions, 'question')}`;
    }
    return { key, label, shortLabel: shortLabel || label.split(' · ')[0], extraQuestions, ...statusTone(key) };
}

/** Chats that wait for the user or stopped on an error belong in Needs you. */
export function goalNeedsAnswer(goal) {
    return ['questions', 'waiting', 'error'].includes(goalStatus(goal)?.key);
}

/** The title of the step the next run works on, shown only when a run is coming. */
export function nextUpStep(goal) {
    if (!isGoalOpen(goal) || goal.next?.kind !== 'wake') return '';
    return goal.next_step || '';
}

/** The paused reason line: what Resume will do. */
export function pausedReason(goal, now = Date.now()) {
    const next = goal?.next;
    if (next?.kind === 'wake') {
        if (next.reason === 'interrupted') return 'When you resume, it runs right away.';
        if (Date.parse(next.at) <= now) return `When you resume, it runs right away. It was set for ${formatRunTime(next.at)}.`;
        return `When you resume, it runs ${formatRunTime(next.at)} as planned.`;
    }
    if (next?.kind === 'wait') return 'When you resume, it keeps waiting for you.';
    if (next?.kind === 'error') return 'When you resume, it shows the error again so you can retry.';
    return '';
}

/** The reason line under the status in goal details. */
export function reasonLine(goal, now = Date.now()) {
    const status = goalStatus(goal, now);
    if (!status) return '';
    if (status.key === 'paused') return pausedReason(goal, now);
    if (['done', 'cancelled', 'error'].includes(status.key)) return '';
    if (status.key === 'waiting') return 'The agent stopped without choosing what to do next.';
    return goal.note || '';
}
