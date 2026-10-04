import { useCallback, useEffect, useId, useRef, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import Modal from '../../components/primitives/Modal.jsx';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import GoalEditor from './GoalEditor.jsx';
import { isGoalOpen, useGoals } from './GoalsState.jsx';
import styles from './GoalPanel.module.css';

/** Shared entry point for the composer menu, /goal, and editing a saved goal. */
export default function GoalDialog({ conversationId, profileId, initialObjective = '', onStarted, onClose }) {
    const { loadGoal, mutateGoal, goalsByConversation } = useGoals();
    const { refetch: refreshConversations } = useConversationCatalog();
    const [snapshot, setSnapshot] = useState(null);
    const [error, setError] = useState('');
    const [attempt, setAttempt] = useState(0);
    const headingId = useId();
    const mounted = useRef(true);

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    const close = () => {
        if (mounted.current) onClose();
    };

    useEffect(() => {
        let active = true;
        setError('');
        void loadGoal(conversationId).then((result) => {
            if (active) setSnapshot(result);
        }).catch((failure) => {
            if (active) setError(failure.message);
        });
        return () => { active = false; };
    }, [conversationId, loadGoal, attempt]);

    const reload = useCallback(async () => {
        const latest = await loadGoal(conversationId);
        setSnapshot(latest);
        return isGoalOpen(latest.goal) ? latest.goal : null;
    }, [conversationId, loadGoal]);

    if (!snapshot) {
        return <Modal onClose={close} labelledBy={headingId}>
            <div className={styles.fields}>
                <h2 id={headingId}>Goal</h2>
                {error ? <>
                    <Callout tone="warning" title="Could not load this chat's goal" description={error} />
                    <Button variant="ghost" onClick={() => setAttempt((value) => value + 1)}>Retry</Button>
                </> : <p role="status">Loading goal…</p>}
                <Button variant="ghost" onClick={close}>Cancel</Button>
            </div>
        </Modal>;
    }

    const goal = isGoalOpen(snapshot.goal) ? snapshot.goal : null;
    const save = async (body) => {
        await mutateGoal(conversationId, goal ? 'edit' : 'create', {
            ...body,
            ...(!goal ? { profile_id: profileId } : {}),
        });
        if (!goal) void refreshConversations();
        if (mounted.current) onStarted?.();
    };

    return <GoalEditor
        key={goal?.id || 'new'}
        goal={goal}
        latestGoal={goalsByConversation[conversationId]}
        initialObjective={initialObjective}
        onSave={save}
        onReload={reload}
        onClose={close}
    />;
}
