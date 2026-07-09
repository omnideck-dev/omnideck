import { useState } from 'react';

import ToggleSwitch from '../ToggleSwitch.jsx';
import { downloadProfileBundle } from '../../utils/bundles.js';
import Button from '../primitives/Button.jsx';
import Modal from '../primitives/Modal.jsx';
import styles from './ExportProfileModal.module.css';

/**
 * Export options for an agent profile. The system prompt and all other
 * settings always travel; the two toggles decide whether the profile's
 * attached skills are embedded in the bundle and whether the bound provider
 * and model come along (off when sharing to an install with a different setup).
 */
export default function ExportProfileModal({ profile, onClose }) {
    const hasSkills = (profile.skills || []).length > 0;
    const [includeSkills, setIncludeSkills] = useState(hasSkills);
    const [includeModel, setIncludeModel] = useState(true);

    const doExport = () => {
        downloadProfileBundle(profile.id, { includeSkills, includeModel });
        onClose();
    };

    return (
        <Modal onClose={onClose} labelledBy="export-profile-title" testId="export-profile-modal">
            <div className={styles.title} id="export-profile-title">
                Export “{profile.name}”
            </div>
            <div className={styles.body}>
                Downloads a file you can import on another install. The system prompt and
                every setting are always included.
            </div>
            <label className={styles.row}>
                <ToggleSwitch
                    checked={includeSkills}
                    onChange={(e) => setIncludeSkills(e.target.checked)}
                    disabled={!hasSkills}
                    data-testid="export-include-skills"
                />
                <span className={styles.rowText}>
                    <span className={styles.rowLabel}>Include attached skills</span>
                    <span className={styles.rowHint}>
                        {hasSkills
                            ? `Includes the ${profile.skills.length} attached skill${profile.skills.length === 1 ? '' : 's'} so the agent arrives complete.`
                            : 'This agent has no attached skills.'}
                    </span>
                </span>
            </label>
            <label className={styles.row}>
                <ToggleSwitch
                    checked={includeModel}
                    onChange={(e) => setIncludeModel(e.target.checked)}
                    data-testid="export-include-model"
                />
                <span className={styles.rowText}>
                    <span className={styles.rowLabel}>Include provider &amp; model</span>
                    <span className={styles.rowHint}>
                        Turn off when the target install uses a different provider or model.
                    </span>
                </span>
            </label>
            <div className={styles.actions}>
                <Button variant="ghost" onClick={onClose} data-testid="export-cancel">
                    Cancel
                </Button>
                <Button variant="filled" onClick={doExport} data-testid="export-confirm">
                    <i className="bi bi-download" /> Export
                </Button>
            </div>
        </Modal>
    );
}
