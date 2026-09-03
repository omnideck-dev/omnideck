import { useEffect, useRef, useState } from 'react';

import IconButton from '../../components/primitives/IconButton.jsx';
import Popover from '../../components/primitives/Popover.jsx';
import { BrowserProfileIcon } from './browserIcons.jsx';
import styles from './BrowserProfileMenu.module.css';

export const EMPTY_BROWSER_PROFILE = 'empty';

function ProfileIcon({ profile }) {
    if (!profile) {
        return <i className="bi bi-slash-circle" aria-hidden="true" />;
    }
    return <BrowserProfileIcon icon={profile.icon} />;
}

export default function BrowserProfileMenu({
    profiles = [],
    value,
    onChange,
    onSave,
    onManage,
}) {
    const triggerRef = useRef(null);
    const itemRefs = useRef([]);
    const [open, setOpen] = useState(false);
    const selectedProfile = profiles.find((profile) => profile.id === value) || null;
    const selectedName = selectedProfile?.name || 'Empty';
    const selectedIndex = selectedProfile
        ? profiles.findIndex((profile) => profile.id === selectedProfile.id)
        : profiles.length;
    const itemCount = profiles.length + 3;

    useEffect(() => {
        if (open) itemRefs.current[selectedIndex]?.focus();
    }, [open, selectedIndex]);

    const close = () => setOpen(false);
    const choose = (profileId) => {
        onChange?.(profileId);
        close();
        triggerRef.current?.focus();
    };
    const runAction = (action) => {
        close();
        action?.();
    };
    const moveFocus = (event, index) => {
        let nextIndex = null;
        if (event.key === 'ArrowDown') nextIndex = (index + 1) % itemCount;
        if (event.key === 'ArrowUp') nextIndex = (index - 1 + itemCount) % itemCount;
        if (event.key === 'Home') nextIndex = 0;
        if (event.key === 'End') nextIndex = itemCount - 1;
        if (nextIndex === null) return;
        event.preventDefault();
        itemRefs.current[nextIndex]?.focus();
    };

    return (
        <div className={styles.root}>
            <button
                ref={triggerRef}
                type="button"
                className={`${styles.trigger} ${open ? styles.triggerOpen : ''}`}
                onClick={() => setOpen((current) => !current)}
                onKeyDown={(event) => {
                    if (event.key !== 'ArrowDown') return;
                    event.preventDefault();
                    setOpen(true);
                }}
                aria-label={`Browser state: ${selectedName}`}
                aria-haspopup="menu"
                aria-expanded={open}
                title={`Browser state: ${selectedName}`}
                data-testid="browser-profile-select"
                data-value={value}
            >
                <span className={styles.triggerIcon}>
                    <ProfileIcon profile={selectedProfile} />
                </span>
                <span className={styles.triggerName}>{selectedName}</span>
                <i className="bi bi-chevron-down" aria-hidden="true" />
            </button>

            {open && (
                <Popover
                    anchorRef={triggerRef}
                    returnFocusRef={triggerRef}
                    onClose={close}
                    align="end"
                    width={300}
                    maxHeight={420}
                    flipThreshold={260}
                    role="menu"
                    ariaLabel="Browser state"
                    testId="browser-profile-select-menu"
                    className={styles.popover}
                >
                    <div className={styles.menuSection}>Load Browser state</div>
                    <div className={styles.profileList}>
                        {profiles.map((profile, index) => (
                            <button
                                ref={(node) => { itemRefs.current[index] = node; }}
                                key={profile.id}
                                type="button"
                                role="menuitemradio"
                                aria-checked={value === profile.id}
                                aria-label={profile.name}
                                className={`${styles.profileOption} ${value === profile.id ? styles.selected : ''}`}
                                onClick={() => choose(profile.id)}
                                onKeyDown={(event) => moveFocus(event, index)}
                                data-value={profile.id}
                            >
                                <span className={styles.profileIcon}>
                                    <ProfileIcon profile={profile} />
                                </span>
                                <span className={styles.profileCopy}>
                                    <span className={styles.profileName}>{profile.name}</span>
                                    <span className={styles.profileDescription}>Saved Browser profile</span>
                                </span>
                                {value === profile.id && <i className="bi bi-check-lg" aria-hidden="true" />}
                            </button>
                        ))}
                        <button
                            ref={(node) => { itemRefs.current[profiles.length] = node; }}
                            type="button"
                            role="menuitemradio"
                            aria-checked={value === EMPTY_BROWSER_PROFILE}
                            aria-label="Empty"
                            className={`${styles.profileOption} ${value === EMPTY_BROWSER_PROFILE ? styles.selected : ''}`}
                            onClick={() => choose(EMPTY_BROWSER_PROFILE)}
                            onKeyDown={(event) => moveFocus(event, profiles.length)}
                            data-value={EMPTY_BROWSER_PROFILE}
                        >
                            <span className={styles.profileIcon}>
                                <ProfileIcon profile={null} />
                            </span>
                            <span className={styles.profileCopy}>
                                <span className={styles.profileName}>Empty</span>
                                <span className={styles.profileDescription}>No saved browser data</span>
                            </span>
                            {value === EMPTY_BROWSER_PROFILE && <i className="bi bi-check-lg" aria-hidden="true" />}
                        </button>
                    </div>

                    <div className={styles.menuSection}>Actions</div>
                    <button
                        ref={(node) => { itemRefs.current[profiles.length + 1] = node; }}
                        type="button"
                        role="menuitem"
                        className={styles.menuAction}
                        onClick={() => runAction(onSave)}
                        onKeyDown={(event) => moveFocus(event, profiles.length + 1)}
                    >
                        <i className="bi bi-camera" aria-hidden="true" />
                        Save Browser state
                    </button>
                    <button
                        ref={(node) => { itemRefs.current[profiles.length + 2] = node; }}
                        type="button"
                        role="menuitem"
                        className={styles.menuAction}
                        onClick={() => runAction(onManage)}
                        onKeyDown={(event) => moveFocus(event, profiles.length + 2)}
                    >
                        <i className="bi bi-gear" aria-hidden="true" />
                        Manage browser profiles
                    </button>
                </Popover>
            )}
            <IconButton
                size="sm"
                className={styles.saveButton}
                onClick={onSave}
                aria-label="Save Browser state"
                title="Save Browser state"
                data-testid="browser-save-state"
            >
                <i className="bi bi-camera" aria-hidden="true" />
            </IconButton>
        </div>
    );
}
