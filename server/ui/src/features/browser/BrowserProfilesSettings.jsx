import { useEffect, useMemo, useState } from 'react';

import ListItem from '../../components/ListItem.jsx';
import SplitPanel from '../../components/SplitPanel.jsx';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import ConfirmButton from '../../components/primitives/ConfirmButton.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import LibraryHeader from '../../components/primitives/LibraryHeader.jsx';
import Modal from '../../components/primitives/Modal.jsx';
import SearchInput from '../../components/primitives/SearchInput.jsx';
import { useDesktopNavigationCommands } from '../navigation/DesktopNavigation.jsx';
import BrowserIconPicker from './BrowserIconPicker.jsx';
import { useBrowserProfilesCatalog } from './BrowserProfilesContext.jsx';
import { BrowserProfileIcon } from './browserIcons.jsx';
import {
    clearBrowserProfileState,
    deleteBrowserProfile,
    removeBrowserProfileSites,
    updateBrowserProfile,
} from './browserApi.js';
import { groupBrowserSites } from './browserSites.js';
import styles from './BrowserProfilesSettings.module.css';

const SITES_PER_PAGE = 6;

function savedDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(date);
}

function siteDataSummary(site) {
    const parts = [];
    if (site.domains.length > 1) parts.push(`${site.domains.length} domains`);
    if (site.cookies) parts.push(`${site.cookies} cookie${site.cookies === 1 ? '' : 's'}`);
    if (site.local_storage) parts.push('Local storage');
    if (site.indexed_db) parts.push('IndexedDB');
    return parts.join(' · ') || 'Saved site data';
}

function profileUsageDescription(loadedInBrowser, assignedAgents) {
    const agentCount = assignedAgents.length;
    if (loadedInBrowser && agentCount > 0) {
        return `Load another profile or Empty in Browser. Also assign ${agentCount === 1 ? 'the agent' : `the ${agentCount} agents`} another Browser profile or Empty, then try again.`;
    }
    if (loadedInBrowser) {
        return 'Load another profile or Empty in Browser, then try again.';
    }
    return `Used by ${agentCount} ${agentCount === 1 ? 'agent' : 'agents'}. Assign ${agentCount === 1 ? 'it' : 'them'} another Browser profile or Empty, then try again.`;
}

export default function BrowserProfilesSettings() {
    const navigation = useDesktopNavigationCommands();
    const {
        profiles,
        loading,
        error: profilesError,
        refresh: refreshProfiles,
        removeProfile,
        upsertProfile,
    } = useBrowserProfilesCatalog();
    const [selectedId, setSelectedId] = useState(null);
    const [draft, setDraft] = useState(null);
    const [profileSearch, setProfileSearch] = useState('');
    const [siteSearch, setSiteSearch] = useState('');
    const [sitePage, setSitePage] = useState(0);
    const [siteToRemove, setSiteToRemove] = useState(null);
    const [removingSite, setRemovingSite] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        setSelectedId((current) => (
            profiles.some((profile) => profile.id === current)
                ? current
                : profiles[0]?.id || null
        ));
    }, [profiles]);

    const selected = useMemo(
        () => profiles.find((profile) => profile.id === selectedId) || null,
        [profiles, selectedId],
    );

    useEffect(() => {
        setDraft((current) => {
            if (!selected) return null;
            const editingSameProfile = current?.profileId === selected.id;
            const hasUnsavedIdentity = editingSameProfile && (
                current.name !== current.baseName || current.icon !== current.baseIcon
            );
            if (hasUnsavedIdentity) return current;
            return {
                profileId: selected.id,
                name: selected.name,
                icon: selected.icon,
                baseName: selected.name,
                baseIcon: selected.icon,
            };
        });
    }, [selected]);

    useEffect(() => {
        setSiteSearch('');
        setSitePage(0);
    }, [selectedId]);

    const filteredProfiles = useMemo(() => {
        const query = profileSearch.trim().toLocaleLowerCase();
        if (!query) return profiles;
        return profiles.filter((profile) => profile.name.toLocaleLowerCase().includes(query));
    }, [profileSearch, profiles]);

    const groupedSitesByProfile = useMemo(() => new Map(
        profiles.map((profile) => [profile.id, groupBrowserSites(profile.sites)]),
    ), [profiles]);

    const selectedSites = groupedSitesByProfile.get(selectedId) || [];

    const filteredSites = useMemo(() => {
        const query = siteSearch.trim().toLocaleLowerCase();
        if (!query) return selectedSites;
        return selectedSites.filter((site) => site.domains.some((domain) => domain.includes(query)));
    }, [selectedSites, siteSearch]);

    const pageCount = Math.max(1, Math.ceil(filteredSites.length / SITES_PER_PAGE));
    const visibleSites = filteredSites.slice(
        sitePage * SITES_PER_PAGE,
        (sitePage + 1) * SITES_PER_PAGE,
    );
    const firstVisibleSite = sitePage * SITES_PER_PAGE + 1;
    const lastVisibleSite = Math.min((sitePage + 1) * SITES_PER_PAGE, filteredSites.length);

    useEffect(() => {
        setSitePage((current) => Math.min(current, pageCount - 1));
    }, [pageCount]);

    const dirty = !!selected && draft?.profileId === selected.id && (
        draft.name !== draft.baseName || draft.icon !== draft.baseIcon
    );

    const save = async () => {
        if (!selected || !draft?.name.trim()) return;
        try {
            const updated = await updateBrowserProfile(selected.id, {
                name: draft.name.trim(),
                icon: draft.icon,
            });
            setDraft({
                profileId: updated.id,
                name: updated.name,
                icon: updated.icon,
                baseName: updated.name,
                baseIcon: updated.icon,
            });
            upsertProfile(updated);
            setError(null);
        } catch (err) {
            setError(err);
        }
    };

    const remove = async () => {
        if (!selected || selected.id === 'default') return;
        try {
            await deleteBrowserProfile(selected.id);
            const remaining = profiles.filter((profile) => profile.id !== selected.id);
            removeProfile(selected.id);
            setSelectedId(remaining[0]?.id || null);
            setError(null);
        } catch (err) {
            setError(err);
        }
    };

    const replaceProfile = (updated) => {
        upsertProfile(updated);
    };

    const removeSite = async (site) => {
        if (!selected) return;
        setRemovingSite(true);
        try {
            replaceProfile(await removeBrowserProfileSites(selected.id, site.domains));
            setSiteToRemove(null);
            setError(null);
        } catch (err) {
            setError(err);
        } finally {
            setRemovingSite(false);
        }
    };

    const clearState = async () => {
        if (!selected) return;
        try {
            replaceProfile(await clearBrowserProfileState(selected.id));
            setError(null);
        } catch (err) {
            setError(err);
        }
    };

    const openSelectedInBrowser = () => {
        if (!selected) return;
        navigation.openBrowser(selected.id, selected.name);
    };

    const displayedError = error || profilesError;
    const profileUsage = error?.details?.usage;
    const loadedInBrowser = profileUsage?.loaded_in_browser === true;
    const assignedAgents = Array.isArray(profileUsage?.agents)
        ? profileUsage.agents
        : [];
    const profileInUse = loadedInBrowser || assignedAgents.length > 0;

    return (
        <div className={styles.page} data-testid="browser-profiles-settings">
            <LibraryHeader
                views={[{ id: 'profiles', label: 'Profiles', count: profiles.length }]}
                activeView="profiles"
                onViewChange={() => {}}
                searchValue={profileSearch}
                onSearchChange={setProfileSearch}
                searchPlaceholder="Search profiles…"
            />

            {displayedError && (
                <div className={styles.error}>
                    <Callout
                        tone="danger"
                        title={profileInUse
                            ? "Can't delete — profile is in use"
                            : 'Browser profile error'}
                        description={profileInUse
                            ? profileUsageDescription(loadedInBrowser, assignedAgents)
                            : displayedError.message}
                    >
                        {assignedAgents.length > 0 && (
                            <Callout.Footnote>
                                {assignedAgents.length === 1 ? 'Agent' : 'Agents'}: {assignedAgents.join(' · ')}
                            </Callout.Footnote>
                        )}
                        {profilesError && !error && (
                            <Callout.Footnote>
                                <button
                                    type="button"
                                    className={styles.retry}
                                    onClick={() => refreshProfiles({ force: true }).catch(() => {})}
                                >
                                    Retry loading profiles
                                </button>
                            </Callout.Footnote>
                        )}
                    </Callout>
                </div>
            )}

            {siteToRemove && (
                <Modal
                    onClose={() => setSiteToRemove(null)}
                    labelledBy="remove-browser-profile-site-title"
                    testId="browser-profile-remove-site-dialog"
                >
                    <div className={styles.dialogTitle} id="remove-browser-profile-site-title">
                        Remove {siteToRemove.domain}?
                    </div>
                    <div className={styles.dialogBody}>
                        This removes its saved sign-in and site data from {selected?.name}.
                    </div>
                    <div className={styles.dialogActions}>
                        <Button
                            variant="ghost"
                            onClick={() => setSiteToRemove(null)}
                            disabled={removingSite}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="danger"
                            onClick={() => removeSite(siteToRemove)}
                            disabled={removingSite}
                            data-testid="browser-profile-confirm-remove-site"
                        >
                            {removingSite ? 'Removing…' : 'Remove site'}
                        </Button>
                    </div>
                </Modal>
            )}

            <SplitPanel className={styles.layout}>
                <SplitPanel.List>
                    <div className={styles.listHeading}>Browser profiles</div>
                    <div className={styles.profileList}>
                        {loading && <div className={styles.empty}>Loading profiles…</div>}
                        {!loading && filteredProfiles.length === 0 && (
                            <div className={styles.empty}>No profiles match your search.</div>
                        )}
                        {filteredProfiles.map((profile) => (
                            <ListItem
                                key={profile.id}
                                active={profile.id === selectedId}
                                onClick={() => setSelectedId(profile.id)}
                                className={styles.profileItem}
                                data-testid={`browser-profile-${profile.id}`}
                                aria-label={`Open ${profile.name}`}
                            >
                                <span className={styles.profileIcon}>
                                    <BrowserProfileIcon icon={profile.icon} />
                                </span>
                                <span className={styles.profileCopy}>
                                    <span className={styles.profileName}>{profile.name}</span>
                                    <span className={styles.profileMeta}>
                                        {groupedSitesByProfile.get(profile.id)?.length || 0} site{groupedSitesByProfile.get(profile.id)?.length === 1 ? '' : 's'}
                                    </span>
                                </span>
                                <i className="bi bi-chevron-right" aria-hidden="true" />
                            </ListItem>
                        ))}
                    </div>
                </SplitPanel.List>

                <SplitPanel.Detail>
                    {selected && draft ? (
                        <div className={styles.detail} data-testid="browser-profile-editor">
                            <div className={styles.detailActions}>
                                {selected.id !== 'default' && (
                                    <ConfirmButton
                                        onConfirm={remove}
                                        label="Delete"
                                        confirmLabel="Delete profile?"
                                        busyLabel="Deleting…"
                                        icon="bi-trash3"
                                        title={`Delete ${selected.name}`}
                                        data-testid="browser-profile-delete"
                                    />
                                )}
                                <ConfirmButton
                                    onConfirm={clearState}
                                    label="Clear profile state"
                                    confirmLabel="Clear all state?"
                                    busyLabel="Clearing…"
                                    icon="bi-eraser"
                                    title={`Clear all saved Browser state from ${selected.name}`}
                                    disabled={selectedSites.length === 0}
                                    data-testid="browser-profile-clear-state"
                                />
                                <span className={styles.actionSpacer} />
                                <Button onClick={openSelectedInBrowser}>
                                    <i className="bi bi-globe2" aria-hidden="true" /> Open in Browser
                                </Button>
                                <Button
                                    variant="filled"
                                    onClick={save}
                                    disabled={!dirty || !draft.name.trim()}
                                >
                                    Save
                                </Button>
                            </div>

                            <div className={styles.detailBody}>
                                <section className={styles.section}>
                                    <div className={styles.sectionLabel}>Identity</div>
                                    <div className={styles.identity}>
                                        <label className={styles.identityLabel} htmlFor="browser-profile-name">Name</label>
                                        <div className={styles.identityPicker}>
                                            <BrowserIconPicker
                                                value={draft.icon}
                                                onChange={(icon) => setDraft((current) => ({ ...current, icon }))}
                                                size="md"
                                            />
                                        </div>
                                        <input
                                            className={styles.identityInput}
                                            id="browser-profile-name"
                                            value={draft.name}
                                            onChange={(event) => setDraft((current) => ({
                                                ...current,
                                                name: event.target.value,
                                            }))}
                                        />
                                        <span className={styles.identitySaved}>Saved {savedDate(selected.updated_at)}</span>
                                    </div>
                                </section>

                                <section className={styles.section}>
                                    <div className={styles.sitesHeading}>
                                        <div>
                                            <h3>Sites in this profile</h3>
                                            <p>
                                                {selectedSites.length} site{selectedSites.length === 1 ? '' : 's'} with saved Browser data
                                            </p>
                                        </div>
                                        {selectedSites.length > SITES_PER_PAGE && (
                                            <SearchInput
                                                value={siteSearch}
                                                onChange={(value) => {
                                                    setSiteSearch(value);
                                                    setSitePage(0);
                                                }}
                                                placeholder="Search sites…"
                                                ariaLabel="Search sites in profile"
                                                className={styles.siteSearch}
                                            />
                                        )}
                                    </div>

                                    <div className={styles.siteList} data-testid="browser-profile-sites">
                                        {visibleSites.map((site) => (
                                            <div className={styles.siteRow} key={site.domain}>
                                                <span className={styles.siteIcon}>
                                                    <i className="bi bi-globe2" aria-hidden="true" />
                                                </span>
                                                <span className={styles.siteCopy}>
                                                    <span className={styles.siteDomain}>{site.domain}</span>
                                                    <span className={styles.siteMeta}>{siteDataSummary(site)}</span>
                                                </span>
                                                <IconButton
                                                    onClick={() => setSiteToRemove(site)}
                                                    className={styles.siteRemove}
                                                    title={`Remove ${site.domain} from this profile`}
                                                    aria-label={`Remove ${site.domain} from this profile`}
                                                    data-testid={`browser-profile-remove-site-${site.domain}`}
                                                >
                                                    <i className="bi bi-trash3" aria-hidden="true" />
                                                </IconButton>
                                            </div>
                                        ))}
                                        {filteredSites.length === 0 && (
                                            <div className={styles.empty}>
                                                {siteSearch ? 'No sites match your search.' : 'No site data saved in this profile.'}
                                            </div>
                                        )}
                                    </div>

                                    {filteredSites.length > SITES_PER_PAGE && (
                                        <nav className={styles.pagination} aria-label="Sites pagination">
                                            <span aria-live="polite">
                                                {firstVisibleSite}–{lastVisibleSite} of {filteredSites.length}
                                            </span>
                                            <div className={styles.pageActions}>
                                                <IconButton
                                                    onClick={() => setSitePage((page) => Math.max(0, page - 1))}
                                                    disabled={sitePage === 0}
                                                    title="Previous page"
                                                    aria-label="Previous sites page"
                                                >
                                                    <i className="bi bi-chevron-left" aria-hidden="true" />
                                                </IconButton>
                                                <IconButton
                                                    onClick={() => setSitePage((page) => Math.min(pageCount - 1, page + 1))}
                                                    disabled={sitePage >= pageCount - 1}
                                                    title="Next page"
                                                    aria-label="Next sites page"
                                                >
                                                    <i className="bi bi-chevron-right" aria-hidden="true" />
                                                </IconButton>
                                            </div>
                                        </nav>
                                    )}
                                </section>
                            </div>
                        </div>
                    ) : (
                        <div className={styles.detailEmpty}>Select a Browser profile.</div>
                    )}
                </SplitPanel.Detail>
            </SplitPanel>
        </div>
    );
}
