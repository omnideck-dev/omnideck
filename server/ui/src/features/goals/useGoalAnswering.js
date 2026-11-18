import { useMemo, useState } from 'react';

import { useGoalQuestionDrafts } from './GoalQuestions.jsx';

function goalAnswers(message) {
    return (message.context || []).filter((item) => item?.type === 'goal_question');
}

export default function useGoalAnswering({ goal, conversationId, queue, onSendAnswers }) {
    const [inFlight, setInFlight] = useState([]);
    const queuedIds = useMemo(() => queue.flatMap((message) => goalAnswers(message)
        .filter((item) => item.goal_id === goal?.id).map((item) => item.question_id)), [queue, goal?.id]);
    const leftOut = useMemo(() => new Set([...queuedIds, ...inFlight.map((answer) => answer.question_id)]),
        [queuedIds, inFlight]);
    const questions = useGoalQuestionDrafts(goal, conversationId, leftOut);
    const [hidden, setHidden] = useState('');
    const [sending, setSending] = useState(false);
    const questionSet = `${goal?.id}:${questions.questions.map((question) => `${question.id}:${question.revision}`).join(',')}`;
    const answering = Boolean(questions.current) && hidden !== questionSet;

    const hasSomethingToSend = questions.answers.length > 0;
    const submit = () => {
        if (!hasSomethingToSend || questions.staleQuestions.length) return;
        const answers = questions.answers;
        setSending(true);
        setInFlight((current) => [...current, ...answers]);
        Promise.resolve(onSendAnswers(goal.id, answers.map((answer) => ({
            question_id: answer.question_id, question_revision: answer.question_revision,
            question: questions.questions.find((question) => question.id === answer.question_id).question,
            answer: answer.answer,
        })))).then((result) => {
            setSending(false);
            if (!result?.queued) questions.clearSubmitted(answers);
            setInFlight((current) => current.filter((answer) => !answers.includes(answer)));
        }, () => {
            setSending(false);
            setInFlight((current) => current.filter((answer) => !answers.includes(answer)));
        });
    };

    const restoreReturned = (messages) => {
        for (const message of messages) {
            if (goalAnswers(message).length) questions.restoreAnswers(message.context);
        }
    };

    const current = questions.current;
    return {
        answering,
        questions,
        text: questions.text,
        setText: questions.setAnswer,
        placeholder: current?.choices?.length ? 'Or type your own answer…' : 'Type your answer…',
        sendLabel: questions.answers.length > 1 ? `Send ${questions.answers.length} answers` : 'Send answer',
        hasSomethingToSend,
        sending,
        canSend: hasSomethingToSend && !questions.staleQuestions.length,
        submit,
        hide: () => setHidden(questionSet),
        show: () => setHidden(''),
        restoreReturned,
    };
}

export function queueRows(queue) {
    return queue.map((message) => {
        const answers = goalAnswers(message).length;
        return answers
            ? { id: message.id, label: `Answers to ${answers} ${answers === 1 ? 'question' : 'questions'}`, editable: false }
            : { id: message.id, label: message.content, editable: true };
    });
}

export function isAnswerMessage(message) {
    return goalAnswers(message).length > 0;
}
