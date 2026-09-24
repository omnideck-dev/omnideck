import { useCallback, useEffect, useState } from 'react';

import { categoryIcon } from './skillCategoryIcons.js';
import Button from '../primitives/Button.jsx';
import Callout from '../primitives/Callout.jsx';
import ConfirmButton from '../primitives/ConfirmButton.jsx';
import styles from './SkillBuilder.module.css';

function _cloneSkill(skill) {
    return JSON.parse(JSON.stringify(skill));
}

// A category backed by an integration carries a boolean `connected`; a static
// category has `connected: null` and so no connection dot.
function isIntegration(category) {
    return category.connected !== null && category.connected !== undefined;
}

export default function SkillBuilder({ skill, categories, onSave, onDelete, onExport }) {
    const [draft, setDraft] = useState(null);
    const [saveError, setSaveError] = useState(null);

    useEffect(() => {
        setSaveError(null);
        setDraft(skill ? _cloneSkill(skill) : null);
    }, [skill]);

    const update = useCallback((field, value) => {
        setDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
    }, []);

    const toggleCategory = useCallback((id) => {
        setDraft((prev) => {
            if (!prev) return prev;
            const current = prev.tool_categories || [];
            const has = current.includes(id);
            return {
                ...prev,
                tool_categories: has ? current.filter((c) => c !== id) : [...current, id],
            };
        });
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
                        <div className={styles.sectionLabel}>Skill text</div>
                        <div className={styles.sectionHelp}>Added to the agent&apos;s instructions when this skill is loaded.</div>
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
                        <div className={styles.sectionLabel}>Tool categories</div>
                        <div className={styles.sectionHelp}>The tool categories this skill grants.</div>
                        <div className={styles.chipGrid}>
                            {categories.map((category) => {
                                const active = (draft.tool_categories || []).includes(category.id);
                                return (
                                    <button
                                        key={category.id}
                                        className={`${styles.chip} ${active ? styles.chipActive : ''}`}
                                        onClick={() => toggleCategory(category.id)}
                                        aria-pressed={active}
                                        data-testid={`cat-chip-${category.id}`}
                                    >
                                        {active && <span className={styles.chipCheck}>&#x2713;</span>}
                                        <i className={`bi ${categoryIcon(category.id)}`} aria-hidden="true" />
                                        {category.label}
                                        {isIntegration(category) && (
                                            <span
                                                className={`${styles.chipDot} ${category.connected ? styles.on : styles.off}`}
                                                title={category.connected ? 'connected' : 'not connected'}
                                                data-testid={`cat-dot-${category.id}`}
                                            />
                                        )}
                                        <span className={styles.chipCnt}>{category.tool_count}</span>
                                    </button>
                                );
                            })}
                        </div>
                    </section>
                </div>
            </div>
        </div>
    );
}
