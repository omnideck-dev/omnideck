import React, { useRef, useState, useEffect, useCallback, useId } from 'react';
import styles from './ChatInput.module.css';
import SendIcon from './icons/SendIcon.jsx';
import StopIcon from './icons/StopIcon.jsx';
import OfflineNotice from './OfflineNotice.jsx';
import ProfileSelector from './ProfileSelector.jsx';
import AttachmentChip from './AttachmentChip.jsx';
import ComposerAddMenu from './ComposerAddMenu.jsx';
import Button from './primitives/Button.jsx';
import SlashHint, { slashOptionId } from './SlashHint.jsx';
import QueueStrip from './QueueStrip.jsx';
import GoalQuestions from '../features/goals/GoalQuestions.jsx';
import useGoalAnswering, { isAnswerMessage, queueRows } from '../features/goals/useGoalAnswering.js';
import { formatRunTime, isGoalOpen } from '../features/goals/goalStatus.js';
import { loadChatDraft, saveChatDraft } from '../utils/chatDraftStorage.js';

// 13.5px font-size * ~1.48 line-height ≈ 20px; 8px top + 4px bottom padding = 12px.
const LINE_HEIGHT_PX = 20;
const PADDING_V_PX = 12;
const MIN_HEIGHT_PX = 44;
const MAX_AUTO_HEIGHT_PX = 8 * LINE_HEIGHT_PX + PADDING_V_PX; // 172px — 8 visible rows
const GOAL_COMMAND = '/goal';

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
    const goalAnswering = useGoalAnswering({ goal, conversationId, queue, onSendAnswers });
    const answering = goalAnswering.answering;
    const message = answering ? goalAnswering.text : chatMessage;
    const setMessage = answering ? goalAnswering.setText : setChatMessage;
    const [selectedProfile, setSelectedProfile] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [isGrown, setIsGrown] = useState(false);

    const textareaRef = useRef(null);
    const fileInputRef = useRef(null);
    const hintId = useId();
    const [hintDismissed, setHintDismissed] = useState('');
    const [slashIndex, setSlashIndex] = useState(0);
    const controlsDisabled = stopRequested || isOffline;
    const goalOpen = isGoalOpen(goal);
    const hasGoalCommand = Boolean(onRequestGoal);
    const attachBlocked = isStreaming;

    const profileName = selectedProfile?.name;
    const placeholder = stopRequested
        ? 'Stopping…'
        : answering
        ? goalAnswering.placeholder
        : isStreaming
        ? 'Message the agent while it works…'
        : `Message ${profileName || 'Omnideck'}…`;
    const goalCommandLabel = goalOpen ? 'Open this chat\'s goal' : 'Start a goal for this chat';
    const slashCommands = [{ command: GOAL_COMMAND, description: goalCommandLabel }];
    const showSlashHint = hasGoalCommand && !answering && !controlsDisabled && message.startsWith('/')
        && !/\s/.test(message) && GOAL_COMMAND.startsWith(message) && hintDismissed !== message;
    const activeSlash = Math.min(slashIndex, slashCommands.length - 1);
    const requestGoalCommand = (objective) => {
        const originalCommand = message;
        onRequestGoal({
            objective,
            onStarted: () => setMessage((current) => current === originalCommand ? '' : current),
            onClosed: () => textareaRef.current?.focus(),
        });
    };
    const pickSlashCommand = (command) => {
        if (command === GOAL_COMMAND && goalOpen) {
            requestGoalCommand('');
            return;
        }
        setMessage(`${command} `);
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
        const onKey = (e) => { if (e.key === 'Escape') setExpanded(false); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [expanded]);

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
            goalAnswering.submit();
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

    useEffect(() => {
        if (!returned.length) return;
        const texts = returned.filter((item) => !isAnswerMessage(item)).map((item) => item.content).filter(Boolean);
        if (texts.length) setChatMessage((current) => [current, ...texts].filter(Boolean).join('\n'));
        goalAnswering.restoreReturned(returned);
        onReturnedConsumed?.(returned.map((item) => item.id));
    }, [returned]);

    const removeQueued = (id) => onRemoveQueued?.(id);
    const editQueued = async (id) => {
        const item = queue.find((queued) => queued.id === id);
        const result = await onRemoveQueued?.(id);
        if (!item || !result?.ok) return;
        goalAnswering.hide();
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
        'aria-autocomplete': showSlashHint ? 'list' : undefined,
        'aria-controls': showSlashHint ? hintId : undefined,
        'aria-activedescendant': showSlashHint ? slashOptionId(hintId, activeSlash) : undefined,
        onKeyDown: (e) => {
            if (showSlashHint && slashCommands.length > 1 && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
                e.preventDefault();
                const step = e.key === 'ArrowDown' ? 1 : -1;
                setSlashIndex((activeSlash + step + slashCommands.length) % slashCommands.length);
                return;
            }
            if (showSlashHint && e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                setHintDismissed(message);
                return;
            }
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (showSlashHint) {
                    pickSlashCommand(slashCommands[activeSlash].command);
                    return;
                }
                handleSubmit(e);
            }
        },
        onPaste: handlePaste,
        placeholder,
        disabled: stopRequested,
    };

    // The corner expand/collapse control appears once the textarea has grown
    // past one row, or whenever the composer is expanded.
    const showCornerBtn = isGrown || expanded;
    const hasSomethingToSend = answering ? goalAnswering.hasSomethingToSend : message.trim().length > 0;

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
            <QueueStrip rows={queueRows(queue)} onRemove={removeQueued} onEdit={editQueued} disabled={isOffline} />
            <form className={styles.inputArea} onSubmit={handleSubmit}>
                <GoalQuestions state={goalAnswering.questions} disabled={controlsDisabled || goalAnswering.sending} paused={Boolean(goal?.paused)} visible={answering}
                    onHide={() => { goalAnswering.hide(); textareaRef.current?.focus(); }}
                    onShow={() => { goalAnswering.show(); textareaRef.current?.focus(); }} />
                {showSlashHint && <SlashHint id={hintId} commands={slashCommands} activeIndex={activeSlash} onPick={pickSlashCommand} />}
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
                        <ComposerAddMenu
                            disabled={controlsDisabled}
                            attachDisabled={attachBlocked}
                            onAttach={() => fileInputRef.current?.click()}
                            goalItem={hasGoalCommand ? {
                                label: goalOpen ? 'Open goal' : 'Start a goal…',
                                shortcut: GOAL_COMMAND,
                                onSelect: () => onRequestGoal({
                                    objective: '',
                                    onStarted: () => {},
                                    onClosed: () => textareaRef.current?.focus(),
                                }),
                            } : null}
                        />
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
                            {isStreaming && (!hasSomethingToSend || stopRequested) ? (
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
                            ) : answering ? (
                                <Button
                                    type="submit"
                                    variant="filled"
                                    loading={goalAnswering.sending && !goalAnswering.hasSomethingToSend}
                                    loadingLabel="Sending…"
                                    disabled={isOffline || stopRequested || !goalAnswering.canSend}
                                >
                                    {goalAnswering.sendLabel}
                                </Button>
                            ) : (
                                <button
                                    type="submit"
                                    className={styles.sendButton}
                                    title="Send message"
                                    aria-label="Send message"
                                    disabled={isOffline || stopRequested || (!message.trim() && (isStreaming || !attachments.length))}
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
