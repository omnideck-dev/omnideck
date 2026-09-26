import React, { useRef, useState, useEffect, useCallback, useMemo } from 'react';
import styles from './ChatInput.module.css';
import PaperclipIcon from './icons/PaperclipIcon.jsx';
import SendIcon from './icons/SendIcon.jsx';
import StopIcon from './icons/StopIcon.jsx';
import OfflineNotice from './OfflineNotice.jsx';
import ProfileSelector from './ProfileSelector.jsx';
import AttachmentChip from './AttachmentChip.jsx';
import ComposerAutocomplete from './ComposerAutocomplete.jsx';
import { loadChatDraft, saveChatDraft } from '../utils/chatDraftStorage.js';
import { detectComposerTrigger, applyComposerToken } from '../hooks/useComposerTrigger.js';
import { useAppData } from '../contexts/AppData.jsx';

// 13.5px font-size * ~1.48 line-height ≈ 20px; 8px top + 4px bottom padding = 12px.
const LINE_HEIGHT_PX = 20;
const PADDING_V_PX = 12;
const MIN_HEIGHT_PX = 44;
const MAX_AUTO_HEIGHT_PX = 8 * LINE_HEIGHT_PX + PADDING_V_PX; // 172px — 8 visible rows

/** Approximate decoded byte size of a base64 string. */
function _base64Bytes(b64) {
    const padding = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0;
    return Math.max(0, Math.floor(b64.length * 3 / 4) - padding);
}

function ChatInput({ onSend, onStop, isStreaming, isOffline = false, stopRequested = false, attachment, draft, onDraftConsumed, selectedProfileId, onProfileChange, profileRefreshSignal, conversationId }) {
    const [message, setMessage] = useState(() => loadChatDraft(conversationId));
    const [selectedProfile, setSelectedProfile] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [isGrown, setIsGrown] = useState(false);
    const [composerTrigger, setComposerTrigger] = useState(null);
    const [composerActiveIndex, setComposerActiveIndex] = useState(0);

    const textareaRef = useRef(null);
    const fileInputRef = useRef(null);
    const pendingCursorRef = useRef(null);
    // An Escape dismiss doesn't change the textarea's value/caret, so the
    // very next re-derive (its own keyup, which onKeyDown's stopPropagation
    // can't reach) would otherwise detect the exact same trigger and reopen
    // the overlay it just closed. Remember what was dismissed and suppress
    // re-detecting that same span until the text actually changes.
    const dismissedRef = useRef(null);

    const { skillsHook, profilesHook } = useAppData();

    // Re-derive the open trigger (if any) from the textarea's own current
    // value/caret — covers typing, arrow-key caret moves, and clicks alike.
    const refreshComposerTrigger = useCallback(() => {
        const el = textareaRef.current;
        if (!el) {
            setComposerTrigger(null);
            return;
        }
        const detected = detectComposerTrigger(el.value, el.selectionStart);
        const dismissed = dismissedRef.current;
        if (
            detected && dismissed
            && detected.triggerIndex === dismissed.triggerIndex
            && el.value === dismissed.text
        ) {
            return;
        }
        if (dismissed && el.value !== dismissed.text) dismissedRef.current = null;
        setComposerTrigger(detected);
    }, []);

    const enabledProfiles = useMemo(
        () => (profilesHook?.profiles || []).filter((p) => p.enabled !== false),
        [profilesHook?.profiles],
    );

    const composerItems = useMemo(() => {
        if (!composerTrigger) return [];
        const query = composerTrigger.query.toLowerCase();
        const pool = composerTrigger.kind === 'agent' ? enabledProfiles : (skillsHook?.skills || []);
        return pool.filter((item) => item.name.toLowerCase().startsWith(query));
    }, [composerTrigger, enabledProfiles, skillsHook?.skills]);

    // While the relevant list is still loading, an open trigger has no items
    // yet through no fault of the user's typing — don't let Enter fall
    // through to a plain send of the raw "/xxx" text just because the
    // overlay hasn't had a chance to populate.
    const composerDataLoading = !!composerTrigger
        && (composerTrigger.kind === 'agent' ? profilesHook?.loading : skillsHook?.loading);

    // The active row resets whenever the filtered list changes shape (new
    // query, items added/removed) so it never points past the new end.
    useEffect(() => {
        setComposerActiveIndex(0);
    }, [composerItems]);

    const commitComposerToken = useCallback((item) => {
        if (!composerTrigger) return;
        const prefix = composerTrigger.kind === 'agent' ? '@' : '/';
        // Names may contain spaces, which the backend's whitespace-delimited
        // token grammar can't parse — fall back to the stable id then.
        const token = /\s/.test(item.name) ? item.id : item.name;
        const { text, cursorIndex } = applyComposerToken(message, composerTrigger, `${prefix}${token}`);
        pendingCursorRef.current = cursorIndex;
        setMessage(text);
        setComposerTrigger(null);
    }, [composerTrigger, message]);

    // Restore the caret to right after the inserted token once the
    // controlled value has actually re-rendered into the textarea.
    useEffect(() => {
        const cursor = pendingCursorRef.current;
        if (cursor == null) return;
        pendingCursorRef.current = null;
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.selectionStart = el.selectionEnd = cursor;
    }, [message]);

    const composerHint = useMemo(() => {
        if (!composerTrigger || !selectedProfile) return null;
        if (composerTrigger.kind === 'agent' && selectedProfile.allow_spawn === false) {
            return `${selectedProfile.name} can't spawn subagents — this may not work as expected.`;
        }
        if (composerTrigger.kind === 'skill' && selectedProfile.allow_load_skills === false) {
            return `${selectedProfile.name} can't load skills — this may not work as expected.`;
        }
        return null;
    }, [composerTrigger, selectedProfile]);

    const profileName = selectedProfile?.name;
    const placeholder = stopRequested
        ? 'Stopping…'
        : isStreaming
        ? `Send a nudge${profileName ? ` to ${profileName}` : ''}…`
        : `Message ${profileName || 'Omnideck'}…`;

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
        saveChatDraft(conversationId, message);
    }, [conversationId, message]);

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
        if (!message.trim() && !attachments.length) return;
        onSend(message.trim(), attachments.length ? attachments : null);
        setMessage('');
        setComposerTrigger(null);
        setAttachments([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        setExpanded(false);
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
        onChange: (e) => {
            setMessage(e.target.value);
            refreshComposerTrigger();
        },
        onKeyDown: (e) => {
            // While the overlay is open, it owns Arrow/Enter/Tab/Escape —
            // this guard runs before both the plain Enter-to-send logic
            // below and the document-level Escape listener that collapses
            // expanded mode (stopPropagation reaches the underlying native
            // event too, per React 17+ root-delegated event semantics).
            if (composerTrigger && (composerItems.length || composerDataLoading)) {
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    e.stopPropagation();
                    if (composerItems.length) {
                        const dir = e.key === 'ArrowDown' ? 1 : -1;
                        setComposerActiveIndex((current) => (current + dir + composerItems.length) % composerItems.length);
                    }
                    return;
                }
                if (e.key === 'Enter' || e.key === 'Tab') {
                    e.preventDefault();
                    e.stopPropagation();
                    // Still loading: swallow this keypress rather than commit
                    // nothing or fall through to sending the raw text.
                    if (composerItems.length) commitComposerToken(composerItems[composerActiveIndex]);
                    return;
                }
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    dismissedRef.current = { triggerIndex: composerTrigger.triggerIndex, text: message };
                    setComposerTrigger(null);
                    return;
                }
            }
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
            }
        },
        onKeyUp: refreshComposerTrigger,
        onClick: refreshComposerTrigger,
        onPaste: handlePaste,
        placeholder,
        disabled: stopRequested,
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
                    {composerItems.length > 0 && (
                        <ComposerAutocomplete
                            anchorRef={textareaRef}
                            items={composerItems}
                            activeIndex={composerActiveIndex}
                            onHover={setComposerActiveIndex}
                            kind={composerTrigger.kind}
                            onCommit={commitComposerToken}
                            onClose={() => setComposerTrigger(null)}
                        />
                    )}
                    {composerHint && (
                        <div className={styles.composerHint}>{composerHint}</div>
                    )}
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
                    <ProfileSelector
                        selectedId={selectedProfileId}
                        onChange={onProfileChange}
                        disabled={isStreaming}
                        refreshSignal={profileRefreshSignal}
                        onSelectedProfile={setSelectedProfile}
                    />
                    <div className={styles.actionButtons}>
                        <button
                            type="button"
                            id="fileButton"
                            className={styles.iconButton}
                            onClick={() => fileInputRef.current && fileInputRef.current.click()}
                            title="Attach file"
                            aria-label="Attach file"
                        >
                            <PaperclipIcon />
                        </button>
                        <input
                            ref={fileInputRef}
                            type="file"
                            id="fileInput"
                            multiple
                            style={{ display: 'none' }}
                            onClick={(e) => { e.target.value = ''; }}
                            onChange={handleFile}
                        />
                        {isStreaming ? (
                            <button
                                type="button"
                                className={`${styles.sendButton} ${styles.stopButton}`}
                                data-testid="chat-stop-btn"
                                title={stopRequested ? 'Stopping…' : 'Stop generation'}
                                aria-label={stopRequested ? 'Stopping' : 'Stop generation'}
                                onClick={onStop}
                                disabled={stopRequested || isOffline}
                            >
                                <StopIcon />
                            </button>
                        ) : (
                            <button
                                type="submit"
                                className={styles.sendButton}
                                title="Send message"
                                aria-label="Send message"
                                disabled={
                                    isOffline
                                    || (!message.trim() && !attachments.length)
                                }
                            >
                                <SendIcon />
                            </button>
                        )}
                    </div>
                </div>
            </form>
        </div>
    );
}

export default ChatInput;
