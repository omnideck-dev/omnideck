import { useEffect, useMemo, useState } from 'react';

import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import Modal from '../../components/primitives/Modal.jsx';
import Select from '../../components/primitives/Select.jsx';
import BrowserIconPicker from './BrowserIconPicker.jsx';
import { useBrowserProfilesCatalog } from './BrowserProfilesContext.jsx';
import { previewBrowserState, saveBrowserState } from './browserApi.js';
import { groupBrowserSites } from './browserSites.js';
import styles from './BrowserSaveModal.module.css';

const NEW_PROFILE = '__new__';

export default function BrowserSaveModal({
    onClose,
    onSaved,
    conversationId = null,
    loadedProfile,
}) {
    const {
        profiles,
        refresh: refreshBrowserProfiles,
        upsertProfile,
    } = useBrowserProfilesCatalog();
    const [sites, setSites] = useState([]);
    const loadedProfileIsKnown = loadedProfile !== undefined;
    const loadedProfileId = loadedProfile?.id ?? null;
    const initialTarget = loadedProfileId || NEW_PROFILE;
    const [target, setTarget] = useState(initialTarget);
    const [sourceProfileId, setSourceProfileId] = useState(loadedProfileId ?? null);
    const [destinationReady, setDestinationReady] = useState(loadedProfileIsKnown);
    const [agentName, setAgentName] = useState('');
    const [previewToken, setPreviewToken] = useState(null);
    const [name, setName] = useState('');
    const [icon, setIcon] = useState('bi-globe2');
    const [assign, setAssign] = useState(false);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        let active = true;
        Promise.all([refreshBrowserProfiles(), previewBrowserState(conversationId)])
            .then(([nextProfiles, preview]) => {
                if (!active) return;
                setSites(preview.sites);
                setPreviewToken(preview.preview_token);
                setAgentName(preview.agent_name || '');
                const availableSource = preview.source_profile_id
                    && nextProfiles.some((profile) => profile.id === preview.source_profile_id)
                    ? preview.source_profile_id
                    : null;
                setSourceProfileId(availableSource);
                if (!loadedProfileIsKnown || preview.source_profile_id !== loadedProfileId) {
                    setTarget(availableSource || NEW_PROFILE);
                }
                setDestinationReady(true);
            })
            .catch((err) => {
                if (active) setError(err.message);
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [conversationId]);

    const options = useMemo(() => {
        const availableProfiles = loadedProfile
            && !profiles.some((profile) => profile.id === loadedProfile.id)
            ? [loadedProfile, ...profiles]
            : profiles;
        const updatableProfiles = conversationId
            ? availableProfiles.filter((profile) => profile.id === sourceProfileId)
            : availableProfiles;
        return [
            ...updatableProfiles.map((profile) => ({ value: profile.id, label: `Update ${profile.name}` })),
            { value: NEW_PROFILE, label: 'Create new profile' },
        ];
    }, [conversationId, loadedProfile, profiles, sourceProfileId]);
    const isNew = target === NEW_PROFILE;
    const targetProfile = profiles.find((profile) => profile.id === target)
        || (loadedProfile?.id === target ? loadedProfile : null);
    const groupedSites = useMemo(() => groupBrowserSites(sites), [sites]);

    const save = async () => {
        if (!previewToken || (isNew && !name.trim())) return;
        setBusy(true);
        setError('');
        try {
            const result = await saveBrowserState({
                conversationId,
                profileId: isNew ? null : target,
                name: name.trim(),
                icon,
                assignToAgent: isNew && assign,
                previewToken,
            });
            upsertProfile(result.profile);
            onSaved?.(result.profile, result.assigned_to_agent, agentName);
            onClose();
        } catch (err) {
            setError(err.message);
        } finally {
            setBusy(false);
        }
    };

    return (
        <Modal onClose={onClose} width={620} labelledBy="save-browser-title" testId="save-browser-modal">
            <div className={styles.header}>
                <div>
                    <h2 id="save-browser-title">Save current Browser as a profile</h2>
                    <p>Create a reusable snapshot of this Browser for agents.</p>
                </div>
                <IconButton className={styles.close} onClick={onClose} title="Close" aria-label="Close">
                    <i className="bi bi-x-lg" />
                </IconButton>
            </div>

            <div className={styles.callout}>
                <Callout
                    tone="info"
                    icon="bi-shield-lock"
                    description="This will allow agents using this profile to access any sites you are logged into."
                />
            </div>

            {!destinationReady ? (
                <div className={styles.loadingState} role="status">
                    <i className="bi bi-arrow-clockwise" aria-hidden="true" />
                    Reading current Browser…
                </div>
            ) : (
                <>
                    <label className={styles.field}>
                        <span>Save as</span>
                        <Select
                            options={options}
                            value={target}
                            onChange={setTarget}
                            disabled={loading}
                            ariaLabel="Save Browser profile destination"
                            className={styles.destination}
                            testId="browser-save-target"
                        />
                    </label>

                    {isNew && (
                        <div className={styles.newProfile}>
                            <div className={styles.identity}>
                                <BrowserIconPicker value={icon} onChange={setIcon} size="md" />
                                <label className={styles.field}>
                                    <span>Profile name</span>
                                    <input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Work accounts" autoFocus />
                                </label>
                            </div>
                            {conversationId && (
                                <label className={styles.assign}>
                                    <input type="checkbox" checked={assign} onChange={(event) => setAssign(event.target.checked)} />
                                    <span>Use this profile for {agentName || 'this agent'} next time</span>
                                </label>
                            )}
                        </div>
                    )}

                    <div className={styles.savedData}>
                        <div className={styles.savedDataTitle}>Sites that will be saved</div>
                        {loading ? (
                            <div className={styles.empty} role="status">Reading current Browser…</div>
                        ) : groupedSites.length ? (
                            <div className={styles.sites}>
                                {groupedSites.map((site) => <span key={site.domain}>{site.domain}</span>)}
                            </div>
                        ) : <div className={styles.empty}>No site data yet.</div>}
                    </div>
                </>
            )}

            {error && (
                <div className={styles.error}>
                    <Callout tone="danger" title="Couldn't save Browser profile" description={error} />
                </div>
            )}
            <div className={styles.footer}>
                <Button onClick={onClose}>Cancel</Button>
                {destinationReady && (
                    <Button
                        variant="filled"
                        onClick={save}
                        disabled={loading || busy || !previewToken || (isNew && !name.trim())}
                        data-testid="browser-save-confirm"
                    >
                        {busy ? 'Saving…' : isNew ? 'Save new profile' : `Update ${targetProfile?.name || 'profile'}`}
                    </Button>
                )}
            </div>
        </Modal>
    );
}
