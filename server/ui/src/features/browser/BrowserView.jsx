import { useEffect, useMemo, useRef, useState } from 'react';

import BrowserPreview from '../../components/BrowserPreview.jsx';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import Modal from '../../components/primitives/Modal.jsx';
import { useDesktopNavigationCommands } from '../navigation/DesktopNavigation.jsx';
import useBrowserControl from '../workspace/useBrowserControl.js';
import { getBrowserSession, loadBrowserSession } from './browserApi.js';
import BrowserProfileMenu, { EMPTY_BROWSER_PROFILE } from './BrowserProfileMenu.jsx';
import BrowserSaveModal from './BrowserSaveModal.jsx';
import { useBrowserProfileLoadRequest } from './BrowserProfileLoadRequest.jsx';
import { useBrowserProfilesCatalog } from './BrowserProfilesContext.jsx';
import styles from './BrowserView.module.css';

export default function BrowserView() {
    const navigation = useDesktopNavigationCommands();
    const { request: profileLoadRequest, clearRequest: clearProfileLoadRequest } = useBrowserProfileLoadRequest();
    const {
        profiles,
        loaded: profilesLoaded,
        replaceProfiles,
    } = useBrowserProfilesCatalog();
    const [session, setSession] = useState(null);
    const [selectedTabId, setSelectedTabId] = useState(null);
    const [pendingLoad, setPendingLoad] = useState(undefined);
    const [pendingLoadName, setPendingLoadName] = useState('');
    const [showSave, setShowSave] = useState(false);
    const [error, setError] = useState('');
    const [sessionKey, setSessionKey] = useState(0);
    const refreshingDeletedProfile = useRef(false);
    const selectedBrowserProfileId = session?.browser_profile_id || EMPTY_BROWSER_PROFILE;
    const loadedProfile = selectedBrowserProfileId !== EMPTY_BROWSER_PROFILE
        ? (profiles.find((profile) => profile.id === selectedBrowserProfileId)
            || session?.profiles?.find((profile) => profile.id === selectedBrowserProfileId))
        : null;

    useEffect(() => {
        getBrowserSession()
            .then((nextSession) => {
                setSession(nextSession);
                replaceProfiles(nextSession.profiles || []);
            })
            .catch((err) => setError(err.message));
    }, []);

    useEffect(() => {
        if (!profileLoadRequest?.profileId || !session) return;
        if (profileLoadRequest.profileId !== selectedBrowserProfileId) {
            setPendingLoadName(profileLoadRequest.profileName || '');
            setPendingLoad(profileLoadRequest.profileId);
        }
        clearProfileLoadRequest();
    }, [clearProfileLoadRequest, profileLoadRequest, selectedBrowserProfileId, session]);

    useEffect(() => {
        const loadedBrowserProfileId = session?.browser_profile_id;
        if (
            !loadedBrowserProfileId
            || loadedBrowserProfileId === EMPTY_BROWSER_PROFILE
            || !profilesLoaded
            || profiles.some((profile) => profile.id === loadedBrowserProfileId)
            || refreshingDeletedProfile.current
        ) return;

        // A profile can be deleted from Settings while Browser remains open.
        // Refresh the server-owned session so the selector does not keep a
        // source profile that no longer exists.
        refreshingDeletedProfile.current = true;
        getBrowserSession()
            .then((nextSession) => {
                setSession(nextSession);
                replaceProfiles(nextSession.profiles || []);
            })
            .catch((err) => setError(err.message))
            .finally(() => {
                refreshingDeletedProfile.current = false;
            });
    }, [profiles, profilesLoaded, replaceProfiles, session?.browser_profile_id]);

    const control = useBrowserControl({
        conversationId: null,
        selectedTabId,
        canControl: true,
        enabled: !!session,
        scope: 'user',
        alwaysEngaged: true,
        sessionKey,
    });

    const tabs = useMemo(() => (control.liveTabs || []).map((tab) => ({
        id: tab.id,
        snapshot: { url: tab.url, title: tab.title, screenshot: null },
    })), [control.liveTabs]);

    useEffect(() => {
        const ids = tabs.map((tab) => tab.id);
        setSelectedTabId((current) => (ids.includes(current) ? current : (ids[0] ?? null)));
    }, [tabs]);

    const profileOptions = useMemo(() => [
        ...profiles.map((profile) => ({ value: profile.id, label: profile.name })),
        { value: EMPTY_BROWSER_PROFILE, label: 'Empty' },
    ], [profiles]);
    const clearPendingLoad = () => {
        setPendingLoad(undefined);
        setPendingLoadName('');
    };

    const replaceSession = async () => {
        setError('');
        try {
            const next = await loadBrowserSession(pendingLoad);
            setSession(next);
            replaceProfiles(next.profiles || []);
            setSelectedTabId(null);
            setSessionKey((value) => value + 1);
            clearPendingLoad();
        } catch (err) {
            setError(err.message);
        }
    };

    return (
        <div className={styles.page} data-testid="browser-page">
            {error && (
                <div className={styles.error}>
                    <Callout tone="danger" title="Browser error" description={error} />
                </div>
            )}
            {tabs.length > 0 ? (
                <BrowserPreview
                    tabs={tabs}
                    selectedId={selectedTabId}
                    onSelectTab={setSelectedTabId}
                    control={control}
                    browserActions={(
                        <BrowserProfileMenu
                            profiles={profiles}
                            value={selectedBrowserProfileId}
                            onChange={(value) => {
                                if (value === selectedBrowserProfileId) return;
                                setPendingLoadName('');
                                setPendingLoad(value);
                            }}
                            onSave={() => setShowSave(true)}
                            onManage={() => navigation.openSettings('browser')}
                        />
                    )}
                />
            ) : (
                <div className={styles.loading}>{session ? 'Opening Browser…' : 'Loading Browser…'}</div>
            )}

            {pendingLoad !== undefined && (
                <Modal onClose={clearPendingLoad} labelledBy="replace-browser-title" testId="replace-browser-modal">
                    <h2 id="replace-browser-title" className={styles.modalTitle}>
                        {pendingLoad === EMPTY_BROWSER_PROFILE ? 'Use Empty?' : `Load ${pendingLoadName || profileOptions.find((option) => option.value === pendingLoad)?.label}?`}
                    </h2>
                    <p className={styles.modalCopy}>
                        Your current tabs and any changes you haven’t saved to a profile will be discarded.
                    </p>
                    <div className={styles.modalActions}>
                        <Button onClick={clearPendingLoad}>Cancel</Button>
                        <Button variant="filled" onClick={replaceSession}>
                            {pendingLoad === EMPTY_BROWSER_PROFILE ? 'Use Empty' : 'Load profile'}
                        </Button>
                    </div>
                </Modal>
            )}

            {showSave && (
                <BrowserSaveModal
                    loadedProfile={loadedProfile}
                    onClose={() => setShowSave(false)}
                    onSaved={() => getBrowserSession().then((nextSession) => {
                        setSession(nextSession);
                        replaceProfiles(nextSession.profiles || []);
                    })}
                />
            )}
        </div>
    );
}
