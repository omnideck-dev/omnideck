import { useState, useEffect } from 'react';
import Select from './primitives/Select.jsx';
import styles from './ProfileSelector.module.css';

export default function ProfileSelector({ selectedId, onChange, disabled, refreshSignal, onSelectedProfile }) {
    const [profiles, setProfiles] = useState([]);

    useEffect(() => {
        let cancelled = false;
        fetch('/api/profiles')
            .then((res) => res.json())
            .then((data) => {
                if (!cancelled) setProfiles(data);
            })
            .catch(() => {});
        return () => { cancelled = true; };
    }, [refreshSignal]);

    useEffect(() => {
        if (profiles.length === 0) return;
        if (!profiles.some((p) => p.id === selectedId)) {
            onChange(profiles[0].id);
        }
    }, [profiles, selectedId, onChange]);

    // Surface the resolved profile so callers can label themselves
    // (e.g. the composer's "Message {profile}" placeholder).
    useEffect(() => {
        if (onSelectedProfile) {
            onSelectedProfile(profiles.find((p) => p.id === selectedId) || null);
        }
    }, [profiles, selectedId, onSelectedProfile]);

    if (profiles.length === 0) return null;

    return (
        <Select
            className={styles.select}
            value={selectedId}
            onChange={onChange}
            disabled={disabled}
            ariaLabel="Agent profile"
            options={profiles.map((profile) => ({
                value: profile.id,
                label: profile.name,
            }))}
        />
    );
}
