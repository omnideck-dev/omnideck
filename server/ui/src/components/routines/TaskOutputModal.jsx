import { useState } from 'react';
import MarkdownContent from '../MarkdownContent.jsx';
import Modal from '../primitives/Modal.jsx';
import styles from './TaskOutputModal.module.css';

/**
 * Full-screen modal for viewing task output with copy functionality.
 */
export default function TaskOutputModal({ output, taskName, runNumber, onClose }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        await navigator.clipboard.writeText(output);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };

    return (
        <Modal
            onClose={onClose}
            width={900}
            labelledBy="task-output-title"
            className={styles.modal}
            testId="task-output-modal"
        >
            <div className={styles.header}>
                <div className={styles.headerInfo}>
                    <div id="task-output-title" className={styles.headerTitle}>Task Output</div>
                    <div className={styles.headerSubtitle}>
                        {taskName} • Run #{runNumber}
                    </div>
                </div>
                <div className={styles.headerActions}>
                    <button
                        className={styles.copyBtn}
                        onClick={handleCopy}
                        aria-label="Copy task output"
                    >
                        {copied ? <><i className="bi bi-check-lg" /> Copied</> : <><i className="bi bi-clipboard" /> Copy</>}
                    </button>
                    <button
                        className={styles.closeBtn}
                        onClick={onClose}
                        aria-label="Close"
                    >
                        <i className="bi bi-x-lg" />
                    </button>
                </div>
            </div>
            <div className={styles.content}>
                {output ? <MarkdownContent>{output}</MarkdownContent> : <p>No output</p>}
            </div>
        </Modal>
    );
}
