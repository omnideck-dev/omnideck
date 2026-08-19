import React, { useRef, useState, useEffect, useCallback } from 'react';
import styles from './ChatInput.module.css';
import PaperclipIcon from './icons/PaperclipIcon.jsx';
import SendIcon from './icons/SendIcon.jsx';
import StopIcon from './icons/StopIcon.jsx';
import OfflineNotice from './OfflineNotice.jsx';
import ProfileSelector from './ProfileSelector.jsx';
import AttachmentChip from './AttachmentChip.jsx';

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

function ChatInput({ onSend, onStop, isStreaming, isOffline = false, stopRequested = false, attachment, draft, onDraftConsumed, selectedProfileId, onProfileChange, profileRefreshSignal }) {
    const [message, setMessage] = useState('');
    const [selectedProfile, setSelectedProfile] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [isGrown, setIsGrown] = useState(false);

    const textareaRef = useRef(null);
    const fileInputRef = useRef(null);

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
        onChange: (e) => setMessage(e.target.value),
        onKeyDown: (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
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
