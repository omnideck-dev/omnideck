import { useEffect, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import { isGoalOpen, plural, unansweredQuestions } from './goalStatus.js';
import styles from './GoalQuestions.module.css';

function draftKey(conversationId, goalId) {
    return `omnideck_goal_answers:${conversationId}:${goalId || ''}`;
}

/** Saved drafts, without those whose question closed or changed since they were typed. */
function readDrafts(key, questions) {
    let drafts;
    try { drafts = JSON.parse(localStorage.getItem(key) || '{}'); } catch { return {}; }
    const current = Object.fromEntries(questions.map((question) => [question.id, question.revision]));
    return Object.fromEntries(Object.entries(drafts).filter(([id, draft]) => current[id] === draft?.revision));
}

function draftAnswer(draft) {
    return (draft?.text?.trim() || draft?.choice || '').trim();
}

export function useGoalQuestionDrafts(goal, conversationId) {
    const key = draftKey(conversationId, goal?.id);
    const questions = isGoalOpen(goal) ? unansweredQuestions(goal) : [];
    const [saved, setSaved] = useState(() => ({ key, drafts: readDrafts(key, questions) }));
    const [selected, setSelected] = useState(null);
    const drafts = saved.key === key ? saved.drafts : readDrafts(key, questions);
    const current = questions.find((q) => q.id === selected) || questions[0];
    const draft = current && drafts[current.id];
    const stale = Boolean(draftAnswer(draft) && draft.revision !== current?.revision);
    const write = (id, value) => setSaved({ key, drafts: { ...drafts, [id]: value } });
    // Typing replaces a picked choice.
    const setAnswer = (text) => {
        if (current) write(current.id, { text, choice: '', revision: current.revision });
    };
    const nextUnanswered = (after, withDrafts) => {
        const index = questions.findIndex((q) => q.id === after);
        const rest = [...questions.slice(index + 1), ...questions.slice(0, index)];
        return rest.find((q) => !draftAnswer(withDrafts[q.id]));
    };
    // A choice marks the answer and moves on to the next question with no answer yet.
    const pickChoice = (choice) => {
        if (!current) return;
        const next = { ...drafts, [current.id]: { text: '', choice, revision: current.revision } };
        setSaved({ key, drafts: next });
        const following = nextUnanswered(current.id, next);
        if (following) setSelected(following.id);
    };
    // Skipping leaves the question open and moves to the next one.
    const skip = () => {
        if (!current || questions.length < 2) return;
        const index = questions.findIndex((q) => q.id === current.id);
        setSelected(questions[(index + 1) % questions.length].id);
    };
    useEffect(() => {
        try { localStorage.setItem(saved.key, JSON.stringify(saved.drafts)); } catch { /* Storage can be unavailable. */ }
    }, [saved]);
    const staleQuestions = questions.filter((question) => draftAnswer(drafts[question.id])
        && drafts[question.id].revision !== question.revision);
    const answers = questions.flatMap((question) => {
        const answer = drafts[question.id];
        return draftAnswer(answer) && answer.revision === question.revision
            ? [{ question_id: question.id, question_revision: question.revision, answer: draftAnswer(answer) }] : [];
    });
    const clearSubmitted = (sent) => setSaved((previous) => {
        const remaining = { ...(previous.key === key ? previous.drafts : drafts) };
        for (const answer of sent) {
            const item = remaining[answer.question_id];
            if (draftAnswer(item) === answer.answer && item.revision === answer.question_revision) delete remaining[answer.question_id];
        }
        return { key, drafts: remaining };
    });
    // Answers the agent never read come back as drafts for the same question version.
    const restoreAnswers = (items) => setSaved((previous) => {
        const next = { ...(previous.key === key ? previous.drafts : drafts) };
        for (const item of items || []) {
            if (item?.type !== 'goal_question' || item.goal_id !== goal?.id) continue;
            const question = questions.find((q) => q.id === item.question_id);
            if (!question || question.revision !== item.question_revision) continue;
            next[item.question_id] = question.choices?.includes(item.answer)
                ? { text: '', choice: item.answer, revision: item.question_revision }
                : { text: item.answer, choice: '', revision: item.question_revision };
        }
        return { key, drafts: next };
    });
    return {
        current, questions, selected: current?.id, select: setSelected, text: draft?.text || '', choice: draft?.choice || '',
        setAnswer, pickChoice, skip, drafted: (id) => Boolean(draftAnswer(drafts[id])), answers, stale, staleQuestions, clearSubmitted, restoreAnswers,
    };
}

export default function GoalQuestions({ state, disabled, queued = false, paused, visible, onHide, onShow }) {
    const { current, questions, selected, select, pickChoice, skip, choice, drafted, stale, staleQuestions, answers } = state;
    if (!current) return null;
    const draftCount = answers.length ? ` · ${answers.length} ${answers.length === 1 ? 'answer' : 'answers'} drafted` : '';
    if (!visible) return <div className={styles.collapsed}>
        <span>{plural(questions.length, 'question')} for you{draftCount}</span>
        <Button variant="ghost" aria-label="Show goal questions" onClick={onShow}>Show</Button>
    </div>;
    const index = questions.findIndex((q) => q.id === selected);
    return <section className={styles.questions} aria-label="Goal questions">
        <div className={styles.heading}>
            <span><i className="bi bi-chat-left-text" aria-hidden="true" /> {questions.length > 1 ? `Question ${index + 1} of ${questions.length}` : 'Question for you'}</span>
            {questions.length > 1 && <span className={styles.marks} role="group" aria-label="Questions">
                {questions.map((question, position) => <button key={question.id} type="button"
                    className={[styles.mark, drafted(question.id) && styles.drafted, question.id === selected && styles.current].filter(Boolean).join(' ')}
                    aria-label={`Question ${position + 1}${drafted(question.id) ? ', answer drafted' : ''}`}
                    aria-current={question.id === selected ? 'true' : undefined}
                    onClick={() => select(question.id)} />)}
            </span>}
            <span className={styles.navigation}>
                {questions.length > 1 && <Button variant="ghost" disabled={disabled} onClick={skip}>Skip for now</Button>}
                <Button variant="ghost" onClick={onHide}>Hide</Button>
            </span>
        </div>
        <p id="goal-current-question" className={styles.question}>{current.question}</p>
        {current.choices.length > 0 && <div className={styles.choices}>{current.choices.map((option) => <Button key={option} wrap
            variant={choice === option ? 'filled' : 'outline'} disabled={disabled} aria-pressed={choice === option}
            onClick={() => pickChoice(option)}>{option}</Button>)}</div>}
        {queued && <p className={styles.notice} role="status">Queued for the agent's next step</p>}
        {stale && <p className={styles.notice} role="status">The question changed. Edit your draft or pick a choice to confirm your answer.</p>}
        {!stale && staleQuestions.length > 0 && <div className={styles.review}>
            <p className={styles.notice} role="status">Another drafted answer needs review because its question changed.</p>
            <Button variant="ghost" onClick={() => select(staleQuestions[0].id)}>Review answer</Button>
        </div>}
        {paused && <p className={styles.notice}>Your answers will be saved. The goal stays paused until you resume it.</p>}
    </section>;
}
