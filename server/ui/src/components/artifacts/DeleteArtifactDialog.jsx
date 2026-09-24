import { useState } from 'react';

import Button from '../primitives/Button.jsx';
import Modal from '../primitives/Modal.jsx';
import styles from './DeleteArtifactDialog.module.css';

/**
 * Confirm removing one artifact. Shown only for artifacts whose file is still
 * present — a missing file is removed without a prompt (nothing to unlink).
 * The checkbox opts into deleting the file from disk as well.
 */
export default function DeleteArtifactDialog({ artifact, onCancel, onConfirm }) {
    const [alsoDeleteFile, setAlsoDeleteFile] = useState(false);

    return (
        <Modal
            onClose={onCancel}
            labelledBy="delete-artifact-title"
            testId="delete-artifact-dialog"
        >
            <div className={styles.title} id="delete-artifact-title">
                Delete &ldquo;{artifact.filename}&rdquo;?
            </div>
            <div className={styles.body}>
                Removes it from the artifacts list. The file stays on disk unless you choose to
                delete it.
            </div>
            <label className={styles.check}>
                <input
                    type="checkbox"
                    checked={alsoDeleteFile}
                    onChange={(e) => setAlsoDeleteFile(e.target.checked)}
                    data-testid="delete-file-checkbox"
                />
                Also delete the file from disk
            </label>
            <div className={styles.path}>{artifact.path}</div>
            <div className={styles.actions}>
                <Button variant="ghost" onClick={onCancel}>Cancel</Button>
                <Button
                    variant="danger"
                    onClick={() => onConfirm({ deleteFile: alsoDeleteFile })}
                    data-testid="confirm-delete"
                >
                    {alsoDeleteFile ? 'Delete file & remove' : 'Remove from list'}
                </Button>
            </div>
        </Modal>
    );
}
