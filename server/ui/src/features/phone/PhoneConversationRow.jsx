import { useEffect, useRef, useState } from 'react';

import ConfirmButton from '../../components/primitives/ConfirmButton.jsx';
import Spinner from '../../components/primitives/Spinner.jsx';
import StatusDot from '../../components/StatusDot.jsx';
import { label, relativeAge } from '../../components/conversationSections.js';
import ConversationGoalStatus from '../goals/ConversationGoalStatus.jsx';
import styles from './PhoneConversationRow.module.css';

const PIN_WIDTH = 84;
const ACTIONS_WIDTH = 160;
const HOLD_MS = 480;
const DRAG_START = 10;

function pointRect(x, y) {
    return { left: x, right: x, top: y, bottom: y };
}

export default function PhoneConversationRow({
    convo,
    running,
    finished,
    showAge = false,
    swipeOffset,
    deleting,
    onOpen,
    onMenu,
    onSwipe,
    onTogglePin,
    onArchive,
    onDelete,
}) {
    const [dragOffset, setDragOffset] = useState(null);
    const gesture = useRef(null);
    const holdTimer = useRef(null);
    const suppressClick = useRef(false);
    const offset = dragOffset ?? swipeOffset;

    useEffect(() => () => clearTimeout(holdTimer.current), []);

    const endHold = () => clearTimeout(holdTimer.current);

    const onPointerDown = (event) => {
        if (event.button !== 0) return;
        suppressClick.current = false;
        gesture.current = { x: event.clientX, y: event.clientY, base: swipeOffset, dragging: false };
        holdTimer.current = setTimeout(() => {
            gesture.current = null;
            suppressClick.current = true;
            onMenu(pointRect(event.clientX, event.clientY));
        }, HOLD_MS);
    };

    const onPointerMove = (event) => {
        const g = gesture.current;
        if (!g) return;
        const dx = event.clientX - g.x;
        const dy = event.clientY - g.y;
        if (!g.dragging) {
            if (Math.abs(dy) > DRAG_START && Math.abs(dy) > Math.abs(dx)) {
                endHold();
                gesture.current = null;
                return;
            }
            if (Math.abs(dx) < DRAG_START) return;
            endHold();
            g.dragging = true;
            event.currentTarget.setPointerCapture?.(event.pointerId);
        }
        setDragOffset(Math.max(-ACTIONS_WIDTH, Math.min(PIN_WIDTH, g.base + dx)));
    };

    const onPointerUp = () => {
        endHold();
        const g = gesture.current;
        gesture.current = null;
        if (!g?.dragging) return;
        suppressClick.current = true;
        const x = dragOffset ?? g.base;
        setDragOffset(null);
        onSwipe(x < -ACTIONS_WIDTH / 2 ? -ACTIONS_WIDTH : x > PIN_WIDTH / 2 ? PIN_WIDTH : 0);
    };

    const onClick = () => {
        if (suppressClick.current) {
            suppressClick.current = false;
            return;
        }
        if (swipeOffset) {
            onSwipe(0);
            return;
        }
        onOpen();
    };

    const id = convo.conversation_id;
    return (
        <div className={styles.swipe} data-testid="phone-conversation" data-conversation-id={id}>
            <div className={`${styles.under} ${styles.underStart}`} aria-hidden={swipeOffset <= 0}>
                <button
                    type="button"
                    className={`${styles.action} ${styles.pin}`}
                    tabIndex={swipeOffset > 0 ? 0 : -1}
                    onClick={onTogglePin}
                    data-testid="phone-swipe-pin"
                >
                    <i className={`bi ${convo.pinned ? 'bi-pin-angle' : 'bi-pin-angle-fill'}`} aria-hidden="true" />
                    {convo.pinned ? 'Unpin' : 'Pin'}
                </button>
            </div>
            <div className={`${styles.under} ${styles.underEnd}`} aria-hidden={swipeOffset >= 0}>
                <button
                    type="button"
                    className={`${styles.action} ${styles.archive}`}
                    tabIndex={swipeOffset < 0 ? 0 : -1}
                    onClick={onArchive}
                    data-testid="phone-swipe-archive"
                >
                    <i className="bi bi-archive" aria-hidden="true" />
                    Archive
                </button>
                <ConfirmButton
                    onConfirm={onDelete}
                    label="Delete"
                    confirmLabel="Confirm?"
                    icon="bi-trash3"
                    disabled={deleting}
                    tabIndex={swipeOffset < 0 ? 0 : -1}
                    className={`${styles.action} ${styles.delete}`}
                    data-testid="phone-swipe-delete"
                />
            </div>
            <div
                className={[styles.row, dragOffset === null ? styles.settling : ''].filter(Boolean).join(' ')}
                style={offset ? { transform: `translateX(${offset}px)` } : undefined}
                role="button"
                tabIndex={0}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
                onClick={onClick}
                onContextMenu={(event) => {
                    event.preventDefault();
                    endHold();
                    onMenu(pointRect(event.clientX, event.clientY));
                }}
                onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onOpen();
                    }
                }}
                data-testid="phone-conversation-row"
            >
                <span className={styles.body}>
                    <span className={styles.title}>{label(convo)}</span>
                    <ConversationGoalStatus conversationId={id} />
                </span>
                {showAge && <span className={styles.age}>{relativeAge(convo.started_at)}</span>}
                {(running || finished) && (
                    <span
                        className={styles.activity}
                        role="img"
                        aria-label={running ? 'Running' : 'Finished'}
                        data-status={running ? 'running' : 'finished'}
                    >
                        {running ? <Spinner /> : <StatusDot status="complete" />}
                    </span>
                )}
            </div>
        </div>
    );
}
