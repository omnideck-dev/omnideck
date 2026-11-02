import { useCallback, useEffect, useState } from 'react';

import ToolSelection from './ToolSelection.jsx';
import Button from '../primitives/Button.jsx';
import Callout from '../primitives/Callout.jsx';
import ConfirmButton from '../primitives/ConfirmButton.jsx';
import styles from './SkillBuilder.module.css';

function _cloneSkill(skill) {
    return JSON.parse(JSON.stringify(skill));
}

export default function SkillBuilder({ skill, categories, onSave, onDelete, onExport, onOpenIntegration }) {
    const [draft, setDraft] = useState(null);
    const [saveError, setSaveError] = useState(null);

    useEffect(() => {
        setSaveError(null);
        setDraft(skill ? _cloneSkill(skill) : null);
    }, [skill]);

    const update = useCallback((field, value) => {
        setDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
    }, []);

    const handleRevert = useCallback(() => {
        if (skill) setDraft(_cloneSkill(skill));
    }, [skill]);

    const handleSave = useCallback(async () => {
        if (!draft || !onSave) return;
        setSaveError(null);
        const result = await onSave(draft);
        if (result && result.ok === false) setSaveError(result.error);
    }, [draft, onSave]);

    if (!skill) {
        return (
            <div className={styles.wrapper}>
                <div className={styles.emptyState}>Select a skill to edit</div>
            </div>
        );
    }

    if (!draft) return null;

    return (
        <div className={styles.wrapper}>
            <div className={styles.editor}>
                <div className={styles.actionsBar}>
                    <ConfirmButton
                        label="Delete"
                        confirmLabel="Confirm?"
                        busyLabel="Deleting…"
                        title="Delete this skill"
                        onConfirm={() => onDelete?.(skill.id)}
                    />
                    <div className={styles.actionsRight}>
                        {!draft._unsaved && (
                            <Button
                                onClick={() => onExport?.(skill.id)}
                                title="Export this skill"
                                data-testid="skill-export"
                            >
                                <i className="bi bi-download" /> Export
                            </Button>
                        )}
                        <Button onClick={handleRevert}>Revert</Button>
                        <Button variant="filled" onClick={handleSave}>Save</Button>
                    </div>
                </div>

                {saveError && (
                    <div className={styles.calloutSlot} data-testid="skill-save-error">
                        <Callout
                            tone="danger"
                            title="Couldn't save"
                            description={saveError.error || saveError.message || 'Please try again.'}
                            onDismiss={() => setSaveError(null)}
                        />
                    </div>
                )}

                <div className={styles.formBody}>
                    <section className={styles.section}>
                        <div className={styles.sectionLabel}>Name</div>
                        <input
                            className={styles.nameInput}
                            type="text"
                            value={draft.name || ''}
                            onChange={(e) => update('name', e.target.value)}
                            placeholder="Skill name"
                            data-testid="skill-name-input"
                        />
                        <input
                            className={styles.textInput}
                            type="text"
                            value={draft.description || ''}
                            onChange={(e) => update('description', e.target.value)}
                            placeholder="Short description"
                            data-testid="skill-desc-input"
                        />
                    </section>

                    <section className={styles.section}>
                        <div className={styles.sectionLabel}>Instructions</div>
                        <div className={styles.sectionHelp}>How should this work be done?</div>
                        <textarea
                            className={styles.promptTextarea}
                            value={draft.prompt || ''}
                            onChange={(e) => update('prompt', e.target.value)}
                            placeholder="Skill instructions…"
                            rows={8}
                            data-testid="skill-prompt"
                        />
                    </section>

                    <section className={styles.section}>
                        <div className={styles.sectionLabel}>Tools</div>
                        <div className={styles.sectionHelp}>Choose what this skill needs.</div>
                        <ToolSelection key={skill.id} categories={categories} categoryIds={draft.tool_categories || []}
                            onCategoriesChange={ids => update('tool_categories', ids)} onOpenIntegration={onOpenIntegration} />
                    </section>
                </div>
            </div>
        </div>
    );
}
