import { useRef, useState } from 'react';

import IconPickerPopover from '../../components/primitives/IconPickerPopover.jsx';
import { BROWSER_PROFILE_ICONS, BrowserProfileIcon } from './browserIcons.jsx';
import styles from './BrowserIconPicker.module.css';

export default function BrowserIconPicker({ value, onChange, size = 'lg' }) {
    const triggerRef = useRef(null);
    const [open, setOpen] = useState(false);

    return (
        <div className={styles.root}>
            <button
                ref={triggerRef}
                type="button"
                className={`${styles.trigger} ${styles[size]}`}
                onClick={() => setOpen((current) => !current)}
                aria-label="Choose profile icon"
                aria-haspopup="menu"
                aria-expanded={open}
                data-testid="browser-icon-picker-trigger"
            >
                <BrowserProfileIcon icon={value} />
            </button>
            {open && (
                <IconPickerPopover
                    anchorRef={triggerRef}
                    returnFocusRef={triggerRef}
                    icons={BROWSER_PROFILE_ICONS}
                    current={value}
                    onPick={(icon) => {
                        onChange(icon);
                        setOpen(false);
                    }}
                    onClose={() => setOpen(false)}
                    ariaLabel="Choose profile icon"
                    testId="browser-icon-picker"
                    optionTestId={(icon) => `browser-icon-${icon}`}
                />
            )}
        </div>
    );
}
