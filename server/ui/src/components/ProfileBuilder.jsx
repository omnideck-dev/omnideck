import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import styles from './ProfileBuilder.module.css';
import ModelPicker from './ModelPicker.jsx';
import ToggleSwitch from './ToggleSwitch.jsx';
import Button from './primitives/Button.jsx';
import Callout from './primitives/Callout.jsx';
import Select from './primitives/Select.jsx';
import IconPickerPopover from './primitives/IconPickerPopover.jsx';
import { AGENT_ICONS, AgentIcon, resolveAgentIcon } from './agents/agentIcons.jsx';
import AgentEditorActions from './agents/AgentEditorActions.jsx';
import { BrowserProfileIcon } from '../features/browser/browserIcons.jsx';
import { EMPTY_BROWSER_PROFILE } from '../features/browser/browserProfileConstants.js';
import { useBrowserProfilesCatalog } from '../features/browser/BrowserProfilesContext.jsx';
import ToolSelection from './skills/ToolSelection.jsx';
import { InferenceSettings, resolvePreset, detectPreset, INFERENCE_FIELDS, isSupported } from './inference';

const clone = value => JSON.parse(JSON.stringify(value));

function SectionHeading({ title, children }) {
    return <header className={styles.sectionHead}><h2>{title}</h2><p>{children}</p></header>;
}

function SettingRow({ icon, title, description, children }) {
    return <label className={styles.settingRow}>
        <i className={`bi ${icon}`} aria-hidden="true" />
        <span className={styles.settingText}><span className={styles.settingTitle}>{title}</span><span className={styles.hint}>{description}</span></span>
        <span className={styles.settingControl}>{children}</span>
    </label>;
}

export default function ProfileBuilder({
    profile, onSave, onDelete, onDuplicate, onExport, onBack, onDirtyChange,
    providers, skills, categories, onOpenIntegration, onOpenSkill,
    deleteConflict, onDismissDeleteConflict,
}) {
    const [draft, setDraft] = useState(null);
    const [baseline, setBaseline] = useState(null);
    const [saveError, setSaveError] = useState(null);
    const [saving, setSaving] = useState(false);
    const [showSaved, setShowSaved] = useState(false);
    const [iconOpen, setIconOpen] = useState(false);
    const iconAnchor = useRef(null);
    const lastBrowser = useRef('default');
    const { profiles: browserProfiles } = useBrowserProfilesCatalog();

    useEffect(() => {
        setSaveError(null);
        setDraft(profile ? clone(profile) : null);
        setBaseline(profile ? clone(profile) : null);
        setIconOpen(false);
        lastBrowser.current = profile?.browser_profile_id || 'default';
    }, [profile]);

    const isDirty = useMemo(() => !!draft && !!baseline && JSON.stringify(draft) !== JSON.stringify(baseline), [draft, baseline]);
    useEffect(() => setShowSaved(false), [profile?.id]);
    useEffect(() => {
        if (isDirty) {
            setShowSaved(false);
            return;
        }
        if (!showSaved) return;
        const timer = setTimeout(() => setShowSaved(false), 3000);
        return () => clearTimeout(timer);
    }, [isDirty, showSaved]);
    useEffect(() => {
        onDirtyChange?.(isDirty);
        return () => onDirtyChange?.(false);
    }, [isDirty, onDirtyChange]);

    const draftProvider = draft?.provider || providers?.[0]?.name || 'ollama';
    const activePreset = useMemo(() => draft ? detectPreset(draft, draftProvider) : null, [draft, draftProvider]);
    const update = useCallback((field, value) => setDraft(prev => prev ? { ...prev, [field]: value } : prev), []);
    const applyPreset = useCallback(presetId => {
        const values = resolvePreset(presetId, draftProvider);
        if (!values) return;
        setDraft(prev => {
            if (!prev) return prev;
            const next = { ...prev };
            for (const key of INFERENCE_FIELDS) next[key] = null;
            for (const [key, value] of Object.entries(values)) if (isSupported(key, draftProvider)) next[key] = value;
            return next;
        });
    }, [draftProvider]);

    const handleSave = async () => {
        if (!draft || saving || (!isDirty && !draft._unsaved) || (draft._unsaved && !draft.model)) return;
        const submitted = clone(draft);
        setSaving(true);
        setShowSaved(false);
        setSaveError(null);
        try {
            const result = await onSave(submitted);
            if (!result?.ok) {
                setSaveError(result?.error || { message: 'Your changes could not be saved. Try again.' });
                return;
            }
            setBaseline(submitted);
            setShowSaved(true);
        } catch {
            setSaveError({ message: 'Your changes could not be saved. Check your connection and try again.' });
        } finally {
            setSaving(false);
        }
    };
    const discard = () => {
        setDraft(clone(baseline));
        lastBrowser.current = baseline.browser_profile_id || 'default';
        setSaveError(null);
        setIconOpen(false);
    };
    if (!profile || !draft) return <div className={styles.emptyState}>Select an agent to edit</div>;
    const pending = isDirty || draft._unsaved;
    return <div className={styles.wrapper}>
        <div className={styles.actionsBar}>
            <Button variant="ghost" onClick={onBack} disabled={saving} data-testid="agent-detail-back"><i className="bi bi-arrow-left" /> Agents</Button>
            <div className={styles.actionsRight}>
                <span className={`${styles.saveStatus} ${isDirty ? styles.pending : draft._unsaved ? styles.notCreated : styles.saved}`} role="status">
                    {isDirty ? <><i className="bi bi-circle-fill" aria-hidden="true" />Unsaved changes</>
                        : draft._unsaved ? 'Not created yet'
                        : showSaved && <span className={styles.savedConfirmation}><i className="bi bi-check2" aria-hidden="true" />Changes saved</span>}
                </span>
                {isDirty && <Button className={styles.discardAction} variant="ghost" disabled={saving} onClick={discard}>Discard</Button>}
                <Button className={styles.saveAction} variant="filled" loading={saving} loadingLabel={draft._unsaved ? 'Creating…' : 'Saving…'} onClick={handleSave}
                    aria-describedby={draft._unsaved && !draft.model ? 'agent-model-required' : undefined}
                    disabled={!pending || (draft._unsaved && !draft.model)}>{draft._unsaved ? 'Create agent' : 'Save'}</Button>
                {!draft._unsaved && <AgentEditorActions disabled={saving}
                    onDuplicate={() => onDuplicate(profile.id)} onExport={() => onExport(profile.id)} onDelete={() => onDelete(profile.id)} />}
            </div>
        </div>
        {deleteConflict && <div className={styles.calloutSlot} data-testid="profile-delete-conflict"><DeleteConflictCallout conflict={deleteConflict} onDismiss={onDismissDeleteConflict} /></div>}
        {saveError && <div className={styles.calloutSlot} data-testid="profile-save-error">
            <Callout tone="danger" title={saveError.error === 'default_agent_cannot_be_disabled' ? "Can't disable the default agent" : "Couldn't save changes"}
                description={saveError.message || 'Try again.'} onDismiss={() => setSaveError(null)} />
        </div>}
        <div className={styles.scroll}>
            <fieldset className={styles.formBody} disabled={saving}>
                <section className={styles.section}>
                    <SectionHeading title="Basics">How the agent is listed and which model it runs on.</SectionHeading>
                    <div className={styles.identity}>
                        <button type="button" className={styles.avatar} ref={iconAnchor} aria-label="Change agent icon"
                            aria-haspopup="menu" aria-expanded={iconOpen} onClick={() => setIconOpen(value => !value)}><AgentIcon icon={draft.icon} /></button>
                        {iconOpen && <IconPickerPopover anchorRef={iconAnchor} onClose={() => setIconOpen(false)}
                            icons={AGENT_ICONS} current={resolveAgentIcon(draft.icon)} ariaLabel="Choose agent icon"
                            onPick={icon => { update('icon', icon); setIconOpen(false); iconAnchor.current?.focus(); }} />}
                        <label className={styles.field}>Name<input className={styles.input} value={draft.name || ''} onChange={e => update('name', e.target.value)} placeholder="Agent name" /></label>
                    </div>
                    <label className={styles.field}>Description<input className={styles.input} value={draft.description || ''}
                        onChange={e => update('description', e.target.value)} placeholder="What this agent is for, in one line" />
                        <span className={styles.hint}>Shown under the name in the Agents list and the agent selector.</span>
                    </label>
                    <div className={styles.field} data-testid="profile-model-picker"><span>Model</span>
                        <ModelPicker providers={providers || []} selectedProvider={draft.provider || null} selectedModel={draft.model || null}
                            onSelect={(provider, model, meta) => setDraft(prev => ({ ...prev, provider: provider || '', model: model || '',
                                ...(meta?.context_window != null ? { context_window: meta.context_window } : {}) }))} inline />
                        {draft._unsaved && !draft.model && <span id="agent-model-required" className={styles.pending} data-testid="profile-model-required">Choose a model to create this agent.</span>}
                    </div>
                    <div data-testid="profile-enabled-toggle"><SettingRow icon="bi-eye" title="Available in chat and to other agents"
                        description="When off, the agent is hidden from the chat panel and other agents can’t start it. Routines that already use it keep running.">
                        <ToggleSwitch checked={draft.enabled !== false} onChange={e => update('enabled', e.target.checked)} aria-label="Available in chat and to other agents" />
                    </SettingRow></div>
                </section>
                <section className={styles.section}>
                    <SectionHeading title="Instructions">Sent to the model at the start of every conversation. Describe the agent’s role, the steps it should follow, and what to avoid. Markdown is supported.</SectionHeading>
                    <textarea className={styles.instructions} aria-label="Instructions" value={draft.system_prompt || ''}
                        onChange={e => update('system_prompt', e.target.value)} placeholder="Instructions for this agent…" rows={12} />
                </section>
                <section className={styles.section}>
                    <SectionHeading title="Skills and tools">Skills describe how to do a type of work. Tools and integrations are the actions the agent can take. Adding a skill also gives the agent the tool groups that skill uses. Select a row to see its tools.</SectionHeading>
                    <ToolSelection key={profile.id} skills={skills} categories={categories} skillIds={draft.skills || []} categoryIds={draft.tool_categories || []}
                        onSkillsChange={ids => update('skills', ids)} onCategoriesChange={ids => update('tool_categories', ids)}
                        onOpenIntegration={onOpenIntegration} onOpenSkill={onOpenSkill} />
                </section>
                <section className={styles.section} data-testid="profile-browser-settings">
                    <SectionHeading title="Browser">Whether the agent can open websites, and which saved browser profile it starts from.</SectionHeading>
                    <SettingRow icon="bi-globe2" title="Let this agent open websites" description="It browses in its own isolated session, separate from your browser.">
                        <ToggleSwitch checked={draft.browser_profile_id !== null} aria-label="Let this agent open websites" onChange={e => {
                            if (!e.target.checked) lastBrowser.current = draft.browser_profile_id || 'default';
                            update('browser_profile_id', e.target.checked ? lastBrowser.current : null);
                        }} />
                    </SettingRow>
                    {draft.browser_profile_id !== null && <div className={styles.subfield}>
                        <label id="agent-browser-profile-label" className={styles.field}>Start from</label>
                        <Select options={[{ value: EMPTY_BROWSER_PROFILE, label: 'Empty' }, ...browserProfiles.map(item => ({ value: item.id, label: item.name }))]}
                            value={draft.browser_profile_id} onChange={value => update('browser_profile_id', value)}
                            ariaLabelledBy="agent-browser-profile-label" testId="agent-browser-profile-select" />
                        <span className={styles.hint}>{draft.browser_profile_id === EMPTY_BROWSER_PROFILE ? 'Empty starts without saved cookies or site data.' : <><BrowserProfileIcon icon={browserProfiles.find(item => item.id === draft.browser_profile_id)?.icon} /> The agent gets an isolated copy of this saved profile.</>}</span>
                    </div>}
                </section>
                <section className={styles.section}>
                    <SectionHeading title="Autonomy">How much the agent can do on its own while working on one request.</SectionHeading>
                    <SettingRow icon="bi-people" title="Delegate tasks to other agents" description="It can start another agent to work on part of a task, then use the result.">
                        <ToggleSwitch checked={draft.allow_spawn !== false} onChange={e => update('allow_spawn', e.target.checked)} aria-label="Delegate tasks to other agents" />
                    </SettingRow>
                    <SettingRow icon="bi-book" title="Load more skills during a conversation" description="If a request needs a skill that isn’t added here, it can load one from your skill library.">
                        <ToggleSwitch checked={draft.allow_load_skills !== false} onChange={e => update('allow_load_skills', e.target.checked)} aria-label="Load more skills during a conversation" />
                    </SettingRow>
                    <SettingRow icon="bi-arrow-repeat" title="Tool steps per message" description="The most tool-call rounds it can take for one message before stopping. Leave empty for unlimited.">
                        <input className={styles.numberInput} type="number" aria-label="Tool steps per message" data-testid="field-max_iterations"
                            min={1} step={1} placeholder="Unlimited" value={draft.max_iterations ?? ''}
                            onChange={e => update('max_iterations', e.target.value === '' ? null : Number(e.target.value))} />
                    </SettingRow>
                </section>
                <details className={styles.modelSettings} key={profile.id}>
                    <summary><i className="bi bi-chevron-right" aria-hidden="true" /><span><span className={styles.modelTitle}>Model settings</span>
                        <span className={styles.hint}>Preset, thinking, sampling and length limits.</span></span></summary>
                    <div className={styles.modelSettingsBody}>
                        <InferenceSettings draft={draft} provider={draftProvider} activePreset={activePreset} onFieldChange={update} onApplyPreset={applyPreset} />
                    </div>
                </details>
            </fieldset>
        </div>
    </div>;
}

function DeleteConflictCallout({ conflict, onDismiss }) {
    const routines = useMemo(() => {
        const seen = new Set();
        const rows = [];
        for (const u of conflict.usage || []) {
            if (seen.has(u.routine_id)) continue;
            seen.add(u.routine_id);
            rows.push({ id: u.routine_id, description: u.routine_description });
        }
        return rows;
    }, [conflict.usage]);

    const description = routines.length === 1
        ? 'Remove this profile from the routine below, then try again.'
        : `Remove this profile from the ${routines.length} routines below, then try again.`;

    return (
        <Callout
            tone="danger"
            title="Can't delete — profile is in use"
            description={description}
            onDismiss={onDismiss}
        >
            <Callout.List>
                {routines.map(g => (
                    <Callout.Item key={g.id} kind="routine">{g.description}</Callout.Item>
                ))}
            </Callout.List>
        </Callout>
    );
}
