import { useRef } from 'react';

import styles from './BrandTabs.module.css';

/**
 * SIGNAL §14 brand tabs.
 *
 * Use for a primary tab set within a panel or settings page. This is distinct
 * from LibraryHeader, which combines subordinate mixed-case views with search.
 *
 * tabs: [{ id, label, count?, disabled?, testId?, panelId? }]
 */
export default function BrandTabs({
    tabs,
    activeTab,
    onTabChange,
    ariaLabel,
    className = '',
    testIdPrefix,
    idBase,
}) {
    const tabRefs = useRef([]);

    const activateFromKeyboard = (event, currentIndex) => {
        const direction = event.key === 'ArrowRight' ? 1
            : event.key === 'ArrowLeft' ? -1
                : 0;
        if (!direction && event.key !== 'Home' && event.key !== 'End') return;

        event.preventDefault();
        let nextIndex = currentIndex;
        if (event.key === 'Home') {
            nextIndex = tabs.findIndex(tab => !tab.disabled);
        } else if (event.key === 'End') {
            for (let index = tabs.length - 1; index >= 0; index -= 1) {
                if (!tabs[index].disabled) {
                    nextIndex = index;
                    break;
                }
            }
        }
        else {
            for (let offset = 1; offset <= tabs.length; offset += 1) {
                const candidate = (currentIndex + (direction * offset) + tabs.length) % tabs.length;
                if (!tabs[candidate].disabled) {
                    nextIndex = candidate;
                    break;
                }
            }
        }

        if (nextIndex < 0 || tabs[nextIndex]?.disabled) return;
        onTabChange(tabs[nextIndex].id);
        tabRefs.current[nextIndex]?.focus();
    };

    return (
        <nav
            className={[styles.tabs, className].filter(Boolean).join(' ')}
            aria-label={ariaLabel}
            role="tablist"
        >
            {tabs.map((tab, index) => {
                const active = tab.id === activeTab;
                const tabId = idBase ? `${idBase}-tab-${tab.id}` : undefined;
                const panelId = tab.panelId
                    || (idBase ? `${idBase}-panel-${tab.id}` : undefined);
                return (
                    <button
                        key={tab.id}
                        ref={element => { tabRefs.current[index] = element; }}
                        type="button"
                        role="tab"
                        id={tabId}
                        aria-controls={panelId}
                        aria-selected={active}
                        tabIndex={active ? 0 : -1}
                        className={[styles.tab, active ? styles.active : ''].filter(Boolean).join(' ')}
                        onClick={() => onTabChange(tab.id)}
                        onKeyDown={event => activateFromKeyboard(event, index)}
                        disabled={tab.disabled}
                        data-testid={tab.testId || (testIdPrefix ? `${testIdPrefix}-${tab.id}` : undefined)}
                    >
                        {tab.label}
                        {tab.count !== undefined && tab.count !== null && (
                            <span className={styles.count}>{tab.count}</span>
                        )}
                    </button>
                );
            })}
        </nav>
    );
}
