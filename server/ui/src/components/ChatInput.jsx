import React, { useRef, useState, useEffect, useCallback, useId } from 'react';
import styles from './ChatInput.module.css';
import PaperclipIcon from './icons/PaperclipIcon.jsx';
import SendIcon from './icons/SendIcon.jsx';
import StopIcon from './icons/StopIcon.jsx';
import OfflineNotice from './OfflineNotice.jsx';
import ProfileSelector from './ProfileSelector.jsx';
import AttachmentChip from './AttachmentChip.jsx';
import Popover from './primitives/Popover.jsx';
import Button from './primitives/Button.jsx';
import SlashHint from './primitives/SlashHint.jsx';
import QueueStrip, { answeredQuestionCount } from './primitives/QueueStrip.jsx';
import GoalQuestions, { useGoalQuestionDrafts } from '../features/goals/GoalQuestions.jsx';
import { formatRunTime, isGoalOpen } from '../features/goals/goalStatus.js';
import { loadChatDraft, saveChatDraft } from '../utils/chatDraftStorage.js';

// 13.5px font-size * ~1.48 line-height ≈ 20px; 8px top + 4px bottom padding = 12px.
const LINE_HEIGHT_PX = 20;
const PADDING_V_PX = 12;
const MIN_HEIGHT_PX = 44;
const MAX_AUTO_HEIGHT_PX = 8 * LINE_HEIGHT_PX + PADDING_V_PX; // 172px — 8 visible rows
const GOAL_COMMAND = '/goal';

function answersSaved(goal, answers) {
    return answers.every((answer) => {
        const question = goal.questions.find((q) => q.id === answer.question_id);
        // Resolved/withdrawn questions have moved out of the working snapshot.
        return !question || question.answers.some((saved) =>
            saved.question_revision === answer.question_revision && saved.answer === answer.answer);
    });
}

/** Stop ends this run only; say what the goal does afterwards. */
function stopTitle(goal) {
    if (!isGoalOpen(goal)) return 'Stop generation';
    const next = goal.next;
    if (next?.kind === 'wake' && Date.parse(next.at) > Date.now()) {
        return `Stops this run. The goal will still run ${formatRunTime(next.at)}.`;
    }
    return 'Stops this run. The goal will wait for you.';
}

/** Approximate decoded byte size of a base64 string. */
function _base64Bytes(b64) {
    const padding = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0;
    return Math.max(0, Math.floor(b64.length * 3 / 4) - padding);
}

const NO_MESSAGES = [];

function ChatInput({ onSend, onSendAnswers, queue = NO_MESSAGES, returned = NO_MESSAGES, onRemoveQueued, onReturnedConsumed, onStop, isStreaming, isOffline = false, stopRequested = false, attachment, draft, onDraftConsumed, selectedProfileId, onProfileChange, profileRefreshSignal, conversationId, onRequestGoal, goal }) {
    const [chatMessage, setChatMessage] = useState(() => loadChatDraft(conversationId));
    const questions = useGoalQuestionDrafts(goal, conversationId);
    const [hiddenQuestions, setHiddenQuestions] = useState('');
    const questionSet = `${goal?.id}:${questions.questions.map((question) => `${question.id}:${question.revision}`).join(',')}`;
    const answering = Boolean(questions.current) && hiddenQuestions !== questionSet;
    const message = answering ? questions.text : chatMessage;
    const setMessage = answering ? questions.setAnswer : setChatMessage;
    const [sendingAnswers, setSendingAnswers] = useState(false);
    // The card locks while its answers wait in the queue.
    const answersQueued = Boolean(goal) && queue.some((item) => (item.context || [])
        .some((entry) => entry?.type === 'goal_question' && entry.goal_id === goal.id));
    const submittedAnswers = useRef([]);
    useEffect(() => {
        if (goal && submittedAnswers.current.length && answersSaved(goal, submittedAnswers.current)) {
            questions.clearSubmitted(submittedAnswers.current);
            setSendingAnswers(false);
            submittedAnswers.current = [];
        }
    }, [goal]);
    const [selectedProfile, setSelectedProfile] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [isGrown, setIsGrown] = useState(false);
    const [addMenuOpen, setAddMenuOpen] = useState(false);

    const textareaRef = useRef(null);
    const fileInputRef = useRef(null);
    const addButtonRef = useRef(null);
    const menuItemRefs = useRef([]);
    const firstMenuFocusRef = useRef(0);
    const menuId = useId();
    const hintId = useId();
    const [hintDismissed, setHintDismissed] = useState('');
    const controlsDisabled = stopRequested || isOffline;
    const closeAddMenu = useCallback(() => setAddMenuOpen(false), []);
    const goalOpen = isGoalOpen(goal);
    const hasGoalCommand = Boolean(onRequestGoal);
    // Queued messages cannot carry files.
    const attachBlocked = isStreaming;

    useEffect(() => {
        if (controlsDisabled) setAddMenuOpen(false);
    }, [controlsDisabled]);

    // Focus moves into the menu once the popover is positioned and visible.
    const focusFirstMenuItem = useCallback(() => {
        const items = menuItemRefs.current.filter(Boolean);
        items[Math.min(firstMenuFocusRef.current, items.length - 1)]?.focus();
    }, []);

    const openAddMenu = (last = false) => {
        if (controlsDisabled) return;
        firstMenuFocusRef.current = last && hasGoalCommand ? 1 : 0;
        setAddMenuOpen(true);
    };

    const handleMenuKeyDown = (event) => {
        const items = menuItemRefs.current.filter(Boolean);
        const index = items.indexOf(document.activeElement);
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            const next = event.key === 'Home' ? 0
                : event.key === 'End' ? items.length - 1
                : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
            items[next]?.focus();
        } else if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            closeAddMenu();
            addButtonRef.current?.focus();
        } else if (event.key === 'Tab') {
            event.preventDefault();
            closeAddMenu();
            const controls = Array.from(addButtonRef.current?.form?.querySelectorAll(
                'button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]):not([type="file"])',
            ) || []);
            const triggerIndex = controls.indexOf(addButtonRef.current);
            const nextControl = controls[triggerIndex + (event.shiftKey ? -1 : 1)];
            (nextControl || addButtonRef.current)?.focus();
        }
    };

    const profileName = selectedProfile?.name;
    const placeholder = stopRequested
        ? 'Stopping…'
        : isStreaming
        ? 'Message the agent while it works…'
        : `Message ${profileName || 'Omnideck'}…`;
    const goalCommandLabel = goalOpen ? 'Open this chat\'s goal' : 'Start a goal for this chat';
    // The hint shows while the text could still become /goal and has no objective yet.
    const showSlashHint = hasGoalCommand && !answering && !controlsDisabled && message.startsWith('/')
        && !/\s/.test(message) && GOAL_COMMAND.startsWith(message) && hintDismissed !== message;
    const requestGoalCommand = (objective) => {
        const originalCommand = message;
        onRequestGoal({
            objective,
            onStarted: () => setMessage((current) => current === originalCommand ? '' : current),
            onClosed: () => textareaRef.current?.focus(),
        });
    };
    const pickSlashCommand = () => {
        if (goalOpen) {
            requestGoalCommand('');
            return;
        }
        setMessage(`${GOAL_COMMAND} `);
        textareaRef.current?.focus();
    };

    const resizeInline = useCallback(() => {
        const el = textareaRef.current;
        if (!el) return;
        if (expanded) {
            // Expanded mode stretches the textarea to fill the chat area via
            // flexbox — clear any height left from auto-sizing so it doesn't
            // snap back to its content height.
            el.style.height = '';
            el.style.overflowY = 'auto';
            return;
        }
        el.style.height = 'auto';
        const h = Math.max(MIN_HEIGHT_PX, Math.min(el.scrollHeight, MAX_AUTO_HEIGHT_PX));
        el.style.height = h + 'px';
        el.style.overflowY = el.scrollHeight > MAX_AUTO_HEIGHT_PX ? 'auto' : 'hidden';
        setIsGrown(h > MIN_HEIGHT_PX);
    }, [expanded]);

    // Re-size whenever message content changes. Also re-run when isGrown flips
    // (toggling paddingRight for the corner button changes wrapping, hence
    // scrollHeight) and when expanding/collapsing.
    useEffect(() => {
        resizeInline();
    }, [message, isGrown, expanded, resizeInline]);

    // Focus the textarea (cursor at end) when expanding. The expanded composer's
    // fill offset is handled in CSS via --titlebar-height, no measurement needed.
    useEffect(() => {
        if (!expanded) return;
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.selectionStart = el.selectionEnd = el.value.length;
    }, [expanded]);

    // ESC collapses the expanded composer without discarding text.
    useEffect(() => {
        if (!expanded) return;
        const onKey = (e) => { if (e.key === 'Escape' && !addMenuOpen) setExpanded(false); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [expanded, addMenuOpen]);

    useEffect(() => {
        if (draft) {
            setMessage(draft);
            onDraftConsumed();
        }
    }, [draft, onDraftConsumed]);

    // Persist the in-progress draft per conversation (component remounts on
    // conversation switch, so this never leaks into a different chat).
    // A brand-new, never-sent conversation gets a fresh id on every page load
    // (nothing anchors it across a reload), so this only survives a hard
    // refresh once the conversation has been sent at least once — by design.
    useEffect(() => {
        saveChatDraft(conversationId, chatMessage);
    }, [conversationId, chatMessage]);

    // Each entry: { base64, content_type, filename, preview } where preview is a
    // data URL for images, null for other file types.
    const [attachments, setAttachments] = useState([]);

    useEffect(() => {
        if (attachment) {
            const { base64, contentType = 'image/png', filename } = attachment;
            const preview = contentType.startsWith('image/')
                ? `data:${contentType};base64,${base64}`
                : null;
            setAttachments(prev => [...prev, { base64, content_type: contentType, filename: filename || null, preview }]);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    }, [attachment]);

    const removeAttachment = (index) => {
        setAttachments(prev => {
            const next = prev.filter((_, i) => i !== index);
            if (next.length === 0 && fileInputRef.current) fileInputRef.current.value = '';
            return next;
        });
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (stopRequested || isOffline) return;
        if (answering) {
            if (!questions.answers.length || questions.staleQuestions.length || sendingAnswers || answersQueued) return;
            const answers = questions.answers;
            submittedAnswers.current = answers;
            setSendingAnswers(true);
            // Send stays off after success until the goal shows the saved answers,
            // so the same answers cannot go out twice. Queued answers lock the
            // card through the queue instead.
            Promise.resolve(onSendAnswers(goal.id, answers.map((answer) => ({
                question_id: answer.question_id, question_revision: answer.question_revision,
                question: questions.questions.find((question) => question.id === answer.question_id).question,
                answer: answer.answer,
            })))).then((result) => {
                if (result?.queued) {
                    setSendingAnswers(false);
                    return;
                }
                if (!result?.goal || answersSaved(result.goal, answers)) {
                    questions.clearSubmitted(answers);
                    return;
                }
                submittedAnswers.current = [];
                setSendingAnswers(false);
            }, () => {
                submittedAnswers.current = [];
                setSendingAnswers(false);
            });
            setExpanded(false);
            return;
        }
        if (!message.trim() && !attachments.length) return;
        if (isStreaming && attachments.length) return;
        const goalCommand = onRequestGoal && message.trim().match(/^\/goal(?:\s+([\s\S]*))?$/);
        if (goalCommand) {
            requestGoalCommand((goalCommand[1] || '').trim());
            return;
        }
        onSend(message.trim(), attachments.length ? attachments : null);
        setMessage('');
        setAttachments([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        setExpanded(false);
    };

    // Messages the run gave back unread return to where they were written:
    // text to the message box, one per line, and answers to the question card.
    useEffect(() => {
        if (!returned.length) return;
        const texts = returned.filter((item) => !answeredQuestionCount(item)).map((item) => item.content).filter(Boolean);
        if (texts.length) setChatMessage((current) => [current, ...texts].filter(Boolean).join('\n'));
        for (const item of returned) {
            if (answeredQuestionCount(item)) questions.restoreAnswers(item.context);
        }
        onReturnedConsumed?.(returned.map((item) => item.id));
    }, [returned]);

    const removeQueued = (item) => onRemoveQueued?.(item.id);
    // Editing takes the message out of the queue and back into the box.
    const editQueued = async (item) => {
        const result = await onRemoveQueued?.(item.id);
        if (!result?.ok) return;
        setHiddenQuestions(questionSet);
        setChatMessage((current) => [current, item.content].filter(Boolean).join('\n'));
        textareaRef.current?.focus();
    };

    const handleFile = (e) => {
        const files = Array.from(e.target.files);
        if (!files.length) return;
        files.forEach(file => {
            const reader = new FileReader();
            reader.onload = (ev) => {
                const base64 = ev.target.result.split(',')[1];
                const preview = file.type.startsWith('image/') ? ev.target.result : null;
                setAttachments(prev => [...prev, { base64, content_type: file.type, filename: file.name, preview }]);
            };
            reader.readAsDataURL(file);
        });
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const handlePaste = (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (ev) => {
                    const base64 = ev.target.result.split(',')[1];
                    const name = `screenshot_${Date.now()}.png`;
                    setAttachments(prev => [...prev, { base64, content_type: file.type, filename: name, preview: ev.target.result }]);
                };
                reader.readAsDataURL(file);
                return;
            }
        }
    };

    const textareaProps = {
        value: message,
        'aria-label': 'Message',
        'aria-describedby': answering ? 'goal-current-question' : undefined,
        onChange: (e) => setMessage(e.target.value),
        'aria-controls': showSlashHint ? hintId : undefined,
        onKeyDown: (e) => {
            if (showSlashHint && e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                setHintDismissed(message);
                return;
            }
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (showSlashHint) {
                    pickSlashCommand();
                    return;
                }
                handleSubmit(e);
            }
        },
        onPaste: handlePaste,
        placeholder,
        disabled: stopRequested || (answering && answersQueued),
    };

    // The corner expand/collapse control appears once the textarea has grown
    // past one row, or whenever the composer is expanded.
    const showCornerBtn = isGrown || expanded;

    return (
        <div className={[
            styles.inputAreaWrapper,
            expanded && styles.expandedWrapper,
        ].filter(Boolean).join(' ')}>
            {isOffline && (
                <OfflineNotice
                    className={styles.offlineNotice}
                    description="Messages and controls are unavailable."
                />
            )}
            <form className={styles.inputArea} onSubmit={handleSubmit}>
                <GoalQuestions state={questions} disabled={controlsDisabled || sendingAnswers || answersQueued} queued={answersQueued} paused={Boolean(goal?.paused)} visible={answering}
                    onHide={() => { setHiddenQuestions(questionSet); textareaRef.current?.focus(); }}
                    onShow={() => { setHiddenQuestions(''); textareaRef.current?.focus(); }} />
                {showSlashHint && <SlashHint id={hintId} command={GOAL_COMMAND} description={goalCommandLabel} onPick={pickSlashCommand} />}
                <QueueStrip messages={queue} onRemove={removeQueued} onEdit={editQueued} disabled={isOffline} />
                {attachBlocked && attachments.length > 0 && <p className={styles.composerNote}>Files can be sent after the agent finishes.</p>}
                {attachments.length > 0 && (
                    <div className={styles.tray}>
                        {attachments.map((att, i) => (
                            <AttachmentChip
                                key={i}
                                src={att.preview || undefined}
                                filename={att.filename}
                                content_type={att.content_type}
                                sizeBytes={att.base64 ? _base64Bytes(att.base64) : undefined}
                                onRemove={() => removeAttachment(i)}
                            />
                        ))}
                    </div>
                )}
                <div className={styles.textareaWrapper}>
                    <textarea
                        ref={textareaRef}
                        {...textareaProps}
                        className={[
                            styles.customInput,
                            showCornerBtn && styles.grown,
                            expanded && styles.expandedInput,
                        ].filter(Boolean).join(' ')}
                    />
                    {showCornerBtn && (
                        <button
                            type="button"
                            className={styles.expandButton}
                            data-testid="composer-expand-btn"
                            onClick={() => setExpanded((v) => !v)}
                            title={expanded ? 'Collapse' : 'Expand'}
                            aria-label={expanded ? 'Collapse input' : 'Expand input'}
                        >
                            <i className={expanded ? 'bi bi-arrows-angle-contract' : 'bi bi-arrows-angle-expand'} />
                        </button>
                    )}
                </div>
                <div className={styles.inputAreaButtons}>
                    <div className={styles.leftActions}>
                        <button
                            ref={addButtonRef}
                            type="button"
                            id="fileButton"
                            className={styles.iconButton}
                            onClick={() => addMenuOpen ? closeAddMenu() : openAddMenu()}
                            onKeyDown={(event) => {
                                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                                    event.preventDefault();
                                    openAddMenu(event.key === 'ArrowUp');
                                }
                            }}
                            title="Add to chat"
                            aria-label="Add to chat"
                            aria-haspopup="menu"
                            aria-expanded={addMenuOpen}
                            aria-controls={addMenuOpen ? menuId : undefined}
                            disabled={controlsDisabled}
                        >
                            <i className={`bi bi-plus ${styles.addIcon}`} aria-hidden="true" />
                        </button>
                        {addMenuOpen && <Popover
                            anchorRef={addButtonRef}
                            onClose={closeAddMenu}
                            onOpen={focusFirstMenuItem}
                            align="start"
                            placement="top"
                            width={232}
                            maxHeight={160}
                            className={styles.addMenu}
                            testId="composer-add-menu"
                        >
                            <div id={menuId} role="menu" aria-label="Add to chat" className={styles.addMenuItems} onKeyDown={handleMenuKeyDown}>
                                <Button
                                    ref={(node) => { menuItemRefs.current[0] = node; }}
                                    variant="menuItem"
                                    role="menuitem"
                                    tabIndex={-1}
                                    disabled={controlsDisabled || attachBlocked}
                                    onClick={() => {
                                        closeAddMenu();
                                        addButtonRef.current?.focus();
                                        fileInputRef.current?.click();
                                    }}
                                >
                                    <PaperclipIcon />
                                    Attach file
                                </Button>
                                {hasGoalCommand && <Button
                                    ref={(node) => { menuItemRefs.current[1] = node; }}
                                    variant="menuItem"
                                    role="menuitem"
                                    tabIndex={-1}
                                    disabled={controlsDisabled}
                                    onClick={() => {
                                        closeAddMenu();
                                        addButtonRef.current?.focus();
                                        onRequestGoal({
                                            objective: '',
                                            onStarted: () => {},
                                            onClosed: () => textareaRef.current?.focus(),
                                        });
                                    }}
                                >
                                    <i className="bi bi-bullseye" aria-hidden="true" />
                                    {goalOpen ? 'Open goal' : 'Start a goal…'}
                                    <span className={styles.menuShortcut}>{GOAL_COMMAND}</span>
                                </Button>}
                            </div>
                        </Popover>}
                        <input
                            ref={fileInputRef}
                            type="file"
                            id="fileInput"
                            multiple
                            aria-label="Choose files to attach"
                            disabled={controlsDisabled || attachBlocked}
                            style={{ display: 'none' }}
                            onClick={(e) => { e.target.value = ''; }}
                            onChange={handleFile}
                        />
                        <ProfileSelector
                            selectedId={selectedProfileId}
                            onChange={onProfileChange}
                            disabled={isStreaming}
                            refreshSignal={profileRefreshSignal}
                            onSelectedProfile={setSelectedProfile}
                        />
                    </div>
                    <div className={styles.actionButtons}>
                        <div className={styles.sendActions}>
                            {isStreaming ? (
                                <button
                                    type="button"
                                    className={`${styles.sendButton} ${styles.stopButton}`}
                                    data-testid="chat-stop-btn"
                                    title={stopRequested ? 'Stopping…' : stopTitle(goal)}
                                    aria-label={stopRequested ? 'Stopping' : 'Stop generation'}
                                    onClick={onStop}
                                    disabled={stopRequested || isOffline}
                                >
                                    <StopIcon />
                                </button>
                            ) : null}
                            {answering ? (
                                <Button
                                    type="submit"
                                    variant="filled"
                                    loading={sendingAnswers}
                                    loadingLabel="Sending…"
                                    disabled={isOffline || stopRequested || answersQueued || questions.staleQuestions.length > 0 || !questions.answers.length}
                                >
                                    {questions.answers.length > 1 ? `Send ${questions.answers.length} answers` : 'Send answer'}
                                </Button>
                            ) : !isStreaming && (
                                <button
                                    type="submit"
                                    className={styles.sendButton}
                                    title="Send message"
                                    aria-label="Send message"
                                    disabled={isOffline || stopRequested || (!message.trim() && !attachments.length)}
                                >
                                    <SendIcon />
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            </form>
        </div>
    );
}

export default ChatInput;
