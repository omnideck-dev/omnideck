import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import styles from './ProfileBuilder.module.css';
import ModelPicker from './ModelPicker.jsx';
import ToggleSwitch from './ToggleSwitch.jsx';
import Button from './primitives/Button.jsx';
import Callout from './primitives/Callout.jsx';
import ConfirmButton from './primitives/ConfirmButton.jsx';
import SearchInput from './primitives/SearchInput.jsx';
import { categoryIcon } from './skills/skillCategoryIcons.js';
import { InferenceSettings, resolvePreset, detectPreset, INFERENCE_FIELDS, isSupported } from './inference';

const HELP_SECTIONS = [
    { title: 'Name', body: 'How this profile appears in the profile list and agent selector.' },
    { title: 'Description', body: 'A short summary of what this profile is tuned for. Shown below the name in the profile list.' },
    { title: 'Model', body: 'The model to use when this profile is active.' },
    { title: 'System Prompt', body: 'Instructions prepended to every conversation. Controls the agent\'s personality, constraints, and behavior. Supports markdown.' },
    { title: 'Skills', body: 'Toggle which tool groups the agent can access. Disabled skills are not available during inference.' },
    { title: 'Inference Preset', body: 'Quick presets that set temperature, sampling, and thinking for common workloads. Selecting a preset fills in the advanced values.' },
    { title: 'Temperature', body: '0.0 = deterministic, 0.7 = general use, 1.0+ = creative. Controls randomness in token selection.' },
    { title: 'Top K', body: 'Limits sampling to the K most probable tokens. 10 = factual, 40 = general, 100+ = creative.' },
    { title: 'Top P', body: 'Nucleus sampling — considers tokens whose cumulative probability exceeds P. 0.5 = focused, 0.9 = general, 1.0 = everything.' },
    { title: 'Repeat Penalty', body: '1.0 = off, 1.1 = general use, 1.5+ = strongly discourages repetition in long outputs.' },
    { title: 'Context Window', body: 'Maximum context window in tokens. Higher values allow longer conversations but use more memory (Ollama only).' },
    { title: 'Max Output (num_predict)', body: 'Maximum tokens the model can generate per turn. -1 = unlimited.' },
    { title: 'Iterations (max_iterations)', body: 'How many tool-call rounds the agent can chain per user message before stopping.' },
    { title: 'Thinking', body: 'When enabled, the model reasons step-by-step before answering. Good for math, logic, and code generation.' },
];

function _cloneProfile(profile) {
    return JSON.parse(JSON.stringify(profile));
}

export default function ProfileBuilder({
    profile,
    onSave,
    onDelete,
    onDuplicate,
    onDirtyChange,
    providers,
    skills,
    categories,
    deleteConflict,
    onDismissDeleteConflict,
}) {
    const [draft, setDraft] = useState(null);
    const [saveError, setSaveError] = useState(null);
    const [showPicker, setShowPicker] = useState(false);
    const [skillSearch, setSkillSearch] = useState('');

    useEffect(() => {
        setSaveError(null);
        if (profile) {
            setDraft(_cloneProfile(profile));
        } else {
            setDraft(null);
        }
    }, [profile]);

    // Unsaved-changes signal for the parent's navigation guard. There's no
    // Revert button, so the parent warns before discarding edits on leave.
    const isDirty = useMemo(() => (
        !!draft && !!profile && JSON.stringify(draft) !== JSON.stringify(profile)
    ), [draft, profile]);
    useEffect(() => {
        onDirtyChange?.(isDirty);
        return () => onDirtyChange?.(false);
    }, [isDirty, onDirtyChange]);

    // Inference-option support (think, top_k, num_ctx, etc.) depends on which
    // provider this profile points at, not on any global default.
    const draftProvider = draft?.provider || providers?.[0]?.name || 'ollama';

    const activePreset = useMemo(() => {
        if (!draft) return null;
        return detectPreset(draft, draftProvider);
    }, [draft, draftProvider]);

    // Skill picker: the library keyed by id, category metadata for chips, and
    // the search-filtered options.
    const skillById = useMemo(() => new Map((skills || []).map((s) => [s.id, s])), [skills]);
    const catById = useMemo(() => new Map((categories || []).map((c) => [c.id, c])), [categories]);
    const visibleSkills = useMemo(() => {
        const q = skillSearch.trim().toLowerCase();
        return q ? (skills || []).filter((s) => s.name.toLowerCase().includes(q)) : (skills || []);
    }, [skills, skillSearch]);
    const skillToolCount = useCallback(
        (skill) => (skill.tool_categories || []).reduce((n, cid) => n + (catById.get(cid)?.tool_count || 0), 0),
        [catById],
    );

    // Dismiss the add-skill popover on outside click or Escape.
    const pickerRef = useRef(null);
    useEffect(() => {
        if (!showPicker) return undefined;
        const onPointerDown = (e) => {
            if (pickerRef.current && !pickerRef.current.contains(e.target)) setShowPicker(false);
        };
        const onKeyDown = (e) => { if (e.key === 'Escape') setShowPicker(false); };
        document.addEventListener('mousedown', onPointerDown);
        document.addEventListener('keydown', onKeyDown);
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [showPicker]);

    const update = useCallback((field, value) => {
        setDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
    }, []);

    const applyPreset = useCallback((presetId) => {
        const values = resolvePreset(presetId, draftProvider);
        if (!values) return;
        setDraft((prev) => {
            if (!prev) return prev;
            const next = { ...prev };
            for (const k of INFERENCE_FIELDS) {
                next[k] = null;
            }
            for (const [k, v] of Object.entries(values)) {
                if (isSupported(k, draftProvider)) {
                    next[k] = v;
                }
            }
            return next;
        });
    }, [draftProvider]);

    const toggleSkill = useCallback((skill) => {
        setDraft((prev) => {
            if (!prev) return prev;
            const current = prev.skills || [];
            const has = current.includes(skill);
            return {
                ...prev,
                skills: has ? current.filter((s) => s !== skill) : [...current, skill],
            };
        });
    }, []);

    const handleSave = useCallback(async () => {
        // A model is required to create a profile, but editing an existing
        // model-less one (e.g. to disable or rename it) stays allowed.
        if (!draft || !onSave || (draft._unsaved && !draft.model)) return;
        setSaveError(null);
        const result = await onSave(draft);
        if (result && result.ok === false && result.error) {
            setSaveError(result.error);
            if (result.error.error === 'default_agent_cannot_be_disabled') {
                setDraft((prev) => (prev ? { ...prev, enabled: true } : prev));
            }
        }
    }, [draft, onSave]);

    if (!profile) {
        return (
            <div className={styles.wrapper}>
                <div className={styles.emptyState}>
                    Select a profile to edit
                </div>
            </div>
        );
    }

    if (!draft) return null;

    return (
        <div className={styles.wrapper}>
            <div className={styles.editor}>
                {/* Actions bar */}
                <div className={styles.actionsBar}>
                        <ConfirmButton
                            label="Delete"
                            confirmLabel="Confirm?"
                            busyLabel="Deleting…"
                            title="Delete this profile"
                            onConfirm={() => onDelete?.(profile.id)}
                        />
                        <div className={styles.actionsRight}>
                            <Button onClick={() => onDuplicate?.(profile.id)}>
                                Duplicate
                            </Button>
                            <Button
                                variant="filled"
                                onClick={handleSave}
                                disabled={draft._unsaved && !draft.model}
                                title={draft._unsaved && !draft.model ? 'Choose a model before saving' : undefined}
                            >
                                Save
                            </Button>
                        </div>
                    </div>

                {deleteConflict && (
                    <div className={styles.calloutSlot} data-testid="profile-delete-conflict">
                        <DeleteConflictCallout
                            conflict={deleteConflict}
                            onDismiss={onDismissDeleteConflict}
                        />
                    </div>
                )}

                <div className={styles.formBody}>
                    {/* 1. Identity */}
                    <section className={styles.section}>
                        <div className={styles.sectionLabel}>Identity</div>
                        <input
                            className={styles.nameInput}
                            type="text"
                            value={draft.name || ''}
                            onChange={(e) => update('name', e.target.value)}
                            placeholder="Profile name"
                        />
                        <input
                            className={styles.textInput}
                            type="text"
                            value={draft.description || ''}
                            onChange={(e) => update('description', e.target.value)}
                            placeholder="Short description"
                            disabled={false}
                        />
                        <label className={styles.enabledToggle} data-testid="profile-enabled-toggle">
                            <input
                                type="checkbox"
                                checked={draft.enabled !== false}
                                onChange={(e) => update('enabled', e.target.checked)}
                            />
                            <span className={styles.enabledToggleLabel}>
                                Enabled
                            </span>
                            <span className={styles.enabledHelp}>
                                Disabled profiles are hidden from the chat panel and can't be used
                                by spawn_agent. Scheduled tasks already using this profile still run.
                            </span>
                        </label>
                        {saveError && saveError.error === 'default_agent_cannot_be_disabled' && (
                            <div className={styles.saveErrorSlot} data-testid="profile-save-error">
                                <Callout
                                    tone="danger"
                                    title="Can't disable the default agent"
                                    description={saveError.message}
                                    onDismiss={() => setSaveError(null)}
                                />
                            </div>
                        )}
                    </section>

                    {/* 2. Provider & Model */}
                    <section className={styles.section} data-testid="profile-model-picker">
                        <div className={styles.sectionLabel}>Provider &amp; Model</div>
                        <ModelPicker
                            providers={providers || []}
                            selectedProvider={draft.provider || null}
                            selectedModel={draft.model || null}
                            onSelect={(p, name, meta) => {
                                setDraft((prev) => {
                                    if (!prev) return prev;
                                    const next = { ...prev, provider: p || '', model: name || '' };
                                    if (meta?.context_window != null) {
                                        next.context_window = meta.context_window;
                                    }
                                    return next;
                                });
                            }}
                            inline
                        />
                        {draft._unsaved && !draft.model && (
                            <div className={styles.modelRequired} data-testid="profile-model-required">
                                Choose a model to create this profile.
                            </div>
                        )}
                    </section>

                    {/* 3. System Prompt */}
                    <section className={styles.section}>
                        <div className={styles.sectionLabel}>System Prompt</div>
                        <textarea
                            className={styles.promptTextarea}
                            value={draft.system_prompt || ''}
                            onChange={(e) => update('system_prompt', e.target.value)}
                            placeholder="System prompt..."
                            rows={8}
                            disabled={false}
                        />
                    </section>

                    {/* 4. Skills — attached chips + add-from-library picker */}
                    <section className={styles.section}>
                        <div className={styles.sectionLabel}>Skills</div>
                        <div className={styles.skillHelp}>Skills this profile loads. Each grants its tool categories to the agent.</div>
                        <div className={styles.pickWrap} ref={pickerRef}>
                            <div className={styles.attached}>
                                {(draft.skills || []).map((id) => {
                                    const rec = skillById.get(id);
                                    return (
                                        <span key={id} className={styles.skChip} data-testid={`profile-skill-${id}`}>
                                            {rec ? rec.name : id}
                                            <button
                                                type="button"
                                                className={styles.skChipX}
                                                title="Remove skill"
                                                aria-label={`Remove ${rec ? rec.name : id}`}
                                                onClick={() => toggleSkill(id)}
                                            >
                                                &#x2715;
                                            </button>
                                        </span>
                                    );
                                })}
                                <button
                                    type="button"
                                    className={styles.addSkillBtn}
                                    onClick={() => setShowPicker((v) => !v)}
                                    data-testid="profile-add-skill"
                                >
                                    <i className="bi bi-plus-lg" /> Add skill
                                </button>
                            </div>
                            {showPicker && (
                                <div className={styles.skPopover} data-testid="profile-skill-picker">
                                    <div className={styles.skPopHead}>
                                        <SearchInput
                                            value={skillSearch}
                                            onChange={setSkillSearch}
                                            placeholder="Search your skills…"
                                        />
                                    </div>
                                    <div className={styles.skPopList}>
                                        {visibleSkills.length === 0 && (
                                            <div className={styles.skPopEmpty}>No skills match.</div>
                                        )}
                                        {visibleSkills.map((s) => {
                                            const on = (draft.skills || []).includes(s.id);
                                            return (
                                                <button
                                                    type="button"
                                                    key={s.id}
                                                    className={`${styles.skPopRow} ${on ? styles.skPopRowOn : ''}`}
                                                    onClick={() => toggleSkill(s.id)}
                                                    data-testid={`profile-skill-option-${s.id}`}
                                                >
                                                    <span className={styles.skPopAdd}>{on ? '✓' : '+'}</span>
                                                    <span className={styles.skPopMain}>
                                                        <span className={styles.skPopName}>{s.name}</span>
                                                        <span className={styles.skPopCats}>
                                                            {(s.tool_categories || []).map((cid) => {
                                                                const cat = catById.get(cid);
                                                                const integration = cat && cat.connected !== null && cat.connected !== undefined;
                                                                return (
                                                                    <span key={cid} className={styles.skPopCat}>
                                                                        <i className={`bi ${categoryIcon(cid)}`} />
                                                                        {cat ? cat.label : cid}
                                                                        {integration && (
                                                                            <span className={`${styles.skPopDot} ${cat.connected ? styles.on : styles.off}`} />
                                                                        )}
                                                                    </span>
                                                                );
                                                            })}
                                                        </span>
                                                    </span>
                                                    <span className={styles.skPopTools}>{skillToolCount(s)} tools</span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                        </div>
                    </section>

                    {/* 5. Autonomy */}
                    <section className={styles.section}>
                        <div className={styles.sectionLabel}>Autonomy</div>
                        <label className={styles.autoRow}>
                            <ToggleSwitch
                                checked={draft.allow_spawn !== false}
                                onChange={(e) => update('allow_spawn', e.target.checked)}
                                aria-label="Allow spawning agents"
                            />
                            <span className={styles.autoText}>
                                <span className={styles.autoLabel}>Allow spawning agents</span>
                                <span className={styles.autoHelp}>The agent can delegate work to sub-agents (spawn_agent).</span>
                            </span>
                        </label>
                        <label className={styles.autoRow}>
                            <ToggleSwitch
                                checked={draft.allow_load_skills !== false}
                                onChange={(e) => update('allow_load_skills', e.target.checked)}
                                aria-label="Allow loading skills mid-conversation"
                            />
                            <span className={styles.autoText}>
                                <span className={styles.autoLabel}>Allow loading skills mid-conversation</span>
                                <span className={styles.autoHelp}>The agent can pull in additional skills on demand (load_skill).</span>
                            </span>
                        </label>
                    </section>

                    {/* 5. Inference (presets + advanced) */}
                    <InferenceSettings
                        key={draft.id}
                        draft={draft}
                        provider={draftProvider}
                        activePreset={activePreset}
                        onFieldChange={update}
                        onApplyPreset={applyPreset}
                    />
                </div>

            </div>

        </div>
    );
}

function DeleteConflictCallout({ conflict, onDismiss }) {
    const goals = useMemo(() => {
        const seen = new Set();
        const rows = [];
        for (const u of conflict.usage || []) {
            if (seen.has(u.goal_id)) continue;
            seen.add(u.goal_id);
            rows.push({ id: u.goal_id, description: u.goal_description });
        }
        return rows;
    }, [conflict.usage]);

    const description = goals.length === 1
        ? 'Remove this profile from the goal below, then try again.'
        : `Remove this profile from the ${goals.length} goals below, then try again.`;

    return (
        <Callout
            tone="danger"
            title="Can't delete — profile is in use"
            description={description}
            onDismiss={onDismiss}
        >
            <Callout.List>
                {goals.map(g => (
                    <Callout.Item key={g.id} kind="goal">{g.description}</Callout.Item>
                ))}
            </Callout.List>
        </Callout>
    );
}
