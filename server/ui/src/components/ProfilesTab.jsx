import { useState, useEffect } from 'react';

import { useAppData } from '../contexts/AppData.jsx';
import useSkills from '../hooks/useSkills.js';
import ProfileList from './ProfileList.jsx';
import ProfileBuilder from './ProfileBuilder.jsx';

export default function ProfilesTab() {
    const { profilesHook } = useAppData();
    const { skills } = useSkills();
    const [providers, setProviders] = useState([]);
    const [categories, setCategories] = useState([]);
    const [draftProfile, setDraftProfile] = useState(null);
    const [deleteConflict, setDeleteConflict] = useState(null);

    useEffect(() => {
        fetch('/api/providers').then(r => r.json()).then(data => {
            setProviders(data.providers || []);
        }).catch(() => {});
    }, []);

    // Tool-category metadata for the skill picker (tool counts, connection dots).
    useEffect(() => {
        fetch('/api/tool-categories').then(r => r.json()).then(data => {
            setCategories(Array.isArray(data) ? data : []);
        }).catch(() => {});
    }, []);

    // Drop any stale conflict when the user switches profiles.
    useEffect(() => {
        setDeleteConflict(null);
    }, [profilesHook.selectedProfileId, draftProfile]);

    const selectedProfile = draftProfile
        ?? profilesHook.profiles.find(p => p.id === profilesHook.selectedProfileId)
        ?? null;

    return (
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
            <ProfileList
                profiles={profilesHook.profiles}
                selectedId={draftProfile ? null : profilesHook.selectedProfileId}
                onSelect={(id) => {
                    setDraftProfile(null);
                    profilesHook.setSelectedProfileId(id);
                }}
                onNew={() => {
                    setDraftProfile({
                        id: `custom_${Date.now()}`,
                        name: 'New Profile',
                        description: '',
                        icon: '🤖',
                        provider: providers[0]?.name || '',
                        model: '',
                        system_prompt: '',
                        skills: [],
                        allow_spawn: true,
                        allow_load_skills: true,
                        _unsaved: true,
                    });
                }}
            />
            <ProfileBuilder
                profile={selectedProfile}
                onSave={async (updated) => {
                    if (updated._unsaved) {
                        const { _unsaved, ...payload } = updated;
                        const created = await profilesHook.createProfile(payload);
                        if (created) {
                            setDraftProfile(null);
                            profilesHook.setSelectedProfileId(created.id);
                        }
                        return { ok: true, data: created };
                    }
                    return profilesHook.updateProfile(updated.id, updated);
                }}
                onDelete={async (id) => {
                    if (draftProfile && draftProfile.id === id) {
                        setDraftProfile(null);
                        setDeleteConflict(null);
                        return;
                    }
                    const result = await profilesHook.deleteProfile(id);
                    setDeleteConflict(result?.conflict ? result : null);
                }}
                deleteConflict={deleteConflict}
                onDismissDeleteConflict={() => setDeleteConflict(null)}
                onDuplicate={async (id) => {
                    if (draftProfile && draftProfile.id === id) return;
                    const result = await profilesHook.duplicateProfile(id);
                    if (result) profilesHook.setSelectedProfileId(result.id);
                }}
                providers={providers}
                skills={skills}
                categories={categories}
            />
        </div>
    );
}
