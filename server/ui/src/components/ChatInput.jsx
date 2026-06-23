import React, { useRef, useState, useEffect, useCallback } from 'react';
import styles from './ChatInput.module.css';
import PaperclipIcon from './icons/PaperclipIcon.jsx';
import SendIcon from './icons/SendIcon.jsx';
import StopIcon from './icons/StopIcon.jsx';
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

function ChatInput({ onSend, onStop, isStreaming, stopRequested = false, attachment, draft, onDraftConsumed, selectedProfileId, onProfileChange, profileRefreshSignal }) {
    const [message, setMessage] = useState('');
    const [selectedProfile, setSelectedProfile] = useState(null);
    const [focusMode, setFocusMode] = useState(false);
    const [isGrown, setIsGrown] = useState(false);

    const textareaRef = useRef(null);
    const focusTextareaRef = useRef(null);
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
        el.style.height = 'auto';
        const h = Math.max(MIN_HEIGHT_PX, Math.min(el.scrollHeight, MAX_AUTO_HEIGHT_PX));
        el.style.height = h + 'px';
        el.style.overflowY = el.scrollHeight > MAX_AUTO_HEIGHT_PX ? 'auto' : 'hidden';
        setIsGrown(h > MIN_HEIGHT_PX);
    }, []);

    // Re-size whenever message content changes. Also re-run when isGrown flips
    // because changing paddingRight (to clear space for the expand button) can
    // alter line-wrapping and therefore scrollHeight.
    useEffect(() => {
        resizeInline();
    }, [message, isGrown, resizeInline]);

    // Re-measure after returning from focus mode — the textarea was covered.
    useEffect(() => {
        if (!focusMode) resizeInline();
    }, [focusMode, resizeInline]);

    // Move focus to the overlay textarea and place cursor at end.
    useEffect(() => {
        if (!focusMode) return;
        const el = focusTextareaRef.current;
        if (!el) return;
        el.focus();
        el.selectionStart = el.selectionEnd = el.value.length;
    }, [focusMode]);

    // ESC collapses focus mode without discarding text.
    useEffect(() => {
        if (!focusMode) return;
        const onKey = (e) => { if (e.key === 'Escape') setFocusMode(false); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [focusMode]);

    useEffect(() => {
        if (draft) {
            setMessage(draft);
            onDraftConsumed();
        }
    }, [draft, onDraftConsumed]);

    const [fileData, setFileData] = useState(null);
    const [filePreview, setFilePreview] = useState(null);
    const [fileName, setFileName] = useState(null);

    useEffect(() => {
        if (attachment) {
            const { base64, contentType = 'image/png', filename } = attachment;
            const dataUrl = `data:${contentType};base64,${base64}`;
            setFileData({ base64, content_type: contentType, filename: filename || null });
            if (contentType.startsWith('image/')) {
                setFilePreview(dataUrl);
            } else {
                setFilePreview(null);
            }
            setFileName(filename || null);
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        }
    }, [attachment]);

    const clearAttachment = () => {
        setFileData(null);
        setFilePreview(null);
        setFileName(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (stopRequested) return;
        if (!message.trim() && !fileData) return;
        onSend(message.trim(), fileData);
        setMessage('');
        clearAttachment();
        setFocusMode(false);
    };

    const handleFile = (e) => {
        const file = e.target.files[0];
        if (!file) {
            clearAttachment();
            return;
        }
        const reader = new FileReader();
        reader.onload = (ev) => {
            const base64 = ev.target.result.split(',')[1];
            setFileData({ base64, content_type: file.type, filename: file.name });
            if (file.type.startsWith('image/')) {
                setFilePreview(ev.target.result);
            } else {
                setFilePreview(null);
            }
            setFileName(file.name);
        };
        reader.readAsDataURL(file);
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
                    setFileData({ base64, content_type: file.type, filename: name });
                    setFilePreview(ev.target.result);
                    setFileName(name);
                };
                reader.readAsDataURL(file);
                return;
            }
        }
    };

    const hasAttachment = filePreview || fileName;

    const sharedTextareaProps = {
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

    return (
        <>
            {/* Single hidden file input shared by both the inline and focus-mode forms. */}
            <input
                ref={fileInputRef}
                type="file"
                style={{ display: 'none' }}
                onClick={(e) => { e.target.value = ''; }}
                onChange={handleFile}
            />

            <div className={styles.inputAreaWrapper}>
                <form className={styles.inputArea} onSubmit={handleSubmit}>
                    {hasAttachment && (
                        <div className={styles.tray}>
                            <AttachmentChip
                                src={filePreview || undefined}
                                filename={fileName}
                                sizeBytes={fileData?.base64 ? _base64Bytes(fileData.base64) : undefined}
                                onRemove={clearAttachment}
                            />
                        </div>
                    )}
                    <div className={styles.textareaWrapper}>
                        <textarea
                            ref={textareaRef}
                            {...sharedTextareaProps}
                            className={styles.customInput}
                            style={isGrown ? { paddingRight: '28px' } : undefined}
                        />
                        {isGrown && (
                            <button
                                type="button"
                                className={styles.expandButton}
                                onClick={() => setFocusMode(true)}
                                title="Expand to full window"
                                aria-label="Expand to full window"
                            >
                                <i className="bi bi-arrows-angle-expand" style={{ fontSize: 11 }} />
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
                                className={styles.iconButton}
                                onClick={() => fileInputRef.current && fileInputRef.current.click()}
                                title="Attach file"
                                aria-label="Attach file"
                            >
                                <PaperclipIcon />
                            </button>
                            {isStreaming ? (
                                <button
                                    type="button"
                                    className={`${styles.sendButton} ${styles.stopButton}`}
                                    title="Stop generation"
                                    aria-label="Stop generation"
                                    onClick={onStop}
                                    disabled={stopRequested}
                                >
                                    <StopIcon />
                                </button>
                            ) : (
                                <button
                                    type="submit"
                                    className={styles.sendButton}
                                    title="Send message"
                                    aria-label="Send message"
                                    disabled={!message.trim() && !fileData}
                                >
                                    <SendIcon />
                                </button>
                            )}
                        </div>
                    </div>
                </form>
            </div>

            {focusMode && (
                <div
                    className={styles.focusOverlay}
                    role="dialog"
                    aria-modal="true"
                    aria-label="Compose message"
                >
                    <div className={styles.focusCard}>
                        <div className={styles.focusHeader}>
                            <span className={styles.focusTitle}>Compose message</span>
                            <button
                                type="button"
                                className={styles.iconButton}
                                onClick={() => setFocusMode(false)}
                                title="Collapse view"
                                aria-label="Collapse view"
                            >
                                <i className="bi bi-arrows-angle-contract" style={{ fontSize: 13 }} />
                            </button>
                        </div>
                        <form className={styles.focusForm} onSubmit={handleSubmit}>
                            {hasAttachment && (
                                <div className={styles.tray}>
                                    <AttachmentChip
                                        src={filePreview || undefined}
                                        filename={fileName}
                                        sizeBytes={fileData?.base64 ? _base64Bytes(fileData.base64) : undefined}
                                        onRemove={clearAttachment}
                                    />
                                </div>
                            )}
                            <textarea
                                ref={focusTextareaRef}
                                {...sharedTextareaProps}
                                className={styles.focusTextarea}
                            />
                            <div className={styles.focusFooter}>
                                <button
                                    type="button"
                                    className={styles.iconButton}
                                    onClick={() => fileInputRef.current && fileInputRef.current.click()}
                                    title="Attach file"
                                    aria-label="Attach file"
                                >
                                    <PaperclipIcon />
                                </button>
                                {isStreaming ? (
                                    <button
                                        type="button"
                                        className={`${styles.sendButton} ${styles.stopButton}`}
                                        title="Stop generation"
                                        aria-label="Stop generation"
                                        onClick={onStop}
                                        disabled={stopRequested}
                                    >
                                        <StopIcon />
                                    </button>
                                ) : (
                                    <button
                                        type="submit"
                                        className={styles.sendButton}
                                        title="Send message"
                                        aria-label="Send message"
                                        disabled={!message.trim() && !fileData}
                                    >
                                        <SendIcon />
                                    </button>
                                )}
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </>
    );
}

export default ChatInput;
