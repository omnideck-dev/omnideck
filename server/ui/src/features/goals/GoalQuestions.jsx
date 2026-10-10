import { useEffect, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import Select from '../../components/primitives/Select.jsx';
import styles from './GoalQuestions.module.css';

function readDrafts(key) {
    try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch { return {}; }
}

export function useGoalQuestionDrafts(goal, conversationId) {
    const key = `omnideck_goal_answers:${conversationId}:${goal?.id || ''}`;
    const [saved, setSaved] = useState(() => ({ key, drafts: readDrafts(key) }));
    const [selected, setSelected] = useState(null);
    const drafts = saved.key === key ? saved.drafts : readDrafts(key);
    const questions = goal && !['completed', 'cancelled'].includes(goal.status)
        ? (goal.questions || []).filter((q) => q.status === 'open' && q.answers.length <= q.reviewed_answer_count) : [];
    const current = questions.find((q) => q.id === selected) || questions[0];
    const draft = current && drafts[current.id];
    const stale = Boolean(draft?.text && draft.revision !== current?.revision);
    const setAnswer = (text) => {
        if (!current) return;
        setSaved({ key, drafts: { ...drafts, [current.id]: { text, revision: current.revision } } });
    };
    useEffect(() => {
        try { localStorage.setItem(saved.key, JSON.stringify(saved.drafts)); } catch { /* Storage can be unavailable. */ }
    }, [saved]);
    const answers = questions.flatMap((q) => {
        const value = drafts[q.id];
        return value?.text?.trim() && value.revision === q.revision
            ? [{ question_id: q.id, question_revision: q.revision, answer: value.text.trim() }] : [];
    });
    return { current, questions, drafts, selected: current?.id, select: setSelected, text: draft?.text || '', setAnswer, answers, stale };
}

export function goalAnswerMessage(questions, answers) {
    return ['Answers to goal questions:', ...answers.flatMap((answer) => [
        '', `[${answer.question_id}] ${questions.find((q) => q.id === answer.question_id).question}`, answer.answer,
    ])].join('\n');
}

export default function GoalQuestions({ state, disabled, paused, chatMode, onChatModeChange }) {
    const { current, questions, drafts, selected, select, setAnswer, text, stale } = state;
    if (!current) return null;
    if (chatMode) return <div className={styles.heading}>
        <span>{questions.length} {questions.length === 1 ? 'question' : 'questions'} for you</span>
        <Button variant="ghost" onClick={() => onChatModeChange(false)}>Answer questions</Button>
    </div>;
    const index = questions.findIndex((q) => q.id === selected);
    return <section className={styles.questions} aria-label="Goal questions">
        <div className={styles.heading}>
            <span><i className="bi bi-chat-left-text" aria-hidden="true" /> {questions.length > 1 ? `Question ${index + 1} of ${questions.length}` : 'Question for you'}</span>
            <div className={styles.navigation}>
                <Button variant="ghost" onClick={() => onChatModeChange(true)}>Chat instead</Button>
            {questions.length > 1 && <>
                <IconButton size="sm" aria-label="Previous question" disabled={index === 0} onClick={() => select(questions[index - 1].id)}><i className="bi bi-chevron-left" /></IconButton>
                <IconButton size="sm" aria-label="Next question" disabled={index === questions.length - 1} onClick={() => select(questions[index + 1].id)}><i className="bi bi-chevron-right" /></IconButton>
            </>}
            </div>
        </div>
        {questions.length > 1 && <Select ariaLabel="Choose a question" value={selected} onChange={select} options={questions.map((q, i) => ({
            value: q.id, label: `${i + 1}. ${q.question}${drafts[q.id]?.text?.trim() ? ' · Draft answer' : ''}`,
        }))} />}
        <p id="goal-current-question" className={styles.question}>{current.question}</p>
        {current.choices.length > 0 && <div className={styles.choices}>{current.choices.map((choice) => <Button key={choice} variant={text === choice ? 'filled' : 'outline'} disabled={disabled} aria-pressed={text === choice} onClick={() => setAnswer(choice)}>{choice}</Button>)}</div>}
        {stale && <p className={styles.notice} role="status">The question changed. Edit your draft or pick a choice to confirm your answer.</p>}
        {paused && <p className={styles.notice}>Your answers will be saved. The goal stays paused until you resume it.</p>}
    </section>;
}

export function GoalQuestionTranscript({ content }) {
    let updates;
    try { updates = JSON.parse(content).question_updates; } catch { return null; }
    if (!Array.isArray(updates) || !updates.length) return null;
    return <div className={styles.transcript} aria-label="Goal question update">
        {updates.map((q) => <div key={`${q.id}:${q.revision}`}><p>{q.question}</p><span className={styles.notice}>{q.status === 'withdrawn' ? 'No longer needed' : q.status === 'resolved' ? 'Resolved' : 'Question for you'}</span></div>)}
    </div>;
}
