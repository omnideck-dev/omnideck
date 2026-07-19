import styles from './TabbedPane.module.css';

/** A tab strip and the content selected by its caller. */
export default function TabbedPane({
    tabs,
    activeTab,
    onTabChange,
    onCloseTab,
    hideTabs = false,
    actions = null,
    children,
}) {
    return (
        <div className={styles.tabbedPane} data-testid="preview-panel">
            {!hideTabs && <div className={styles.tabBar} data-testid="preview-tab-bar">
                <div className={styles.tabList}>
                    {tabs.map((tab) => {
                        const isActive = tab.id === activeTab;
                        return (
                            <button
                                key={tab.id}
                                className={`${styles.tab} ${isActive ? styles.tabActive : ''}`}
                                onClick={() => onTabChange(tab.id)}
                                title={tab.label}
                                data-testid={`preview-tab-${tab.testid || tab.id}`}
                            >
                                <span className={styles.tabIcon}>{tab.icon}</span>
                                <span className={styles.tabLabel}>{tab.label}</span>
                                <span
                                    className={styles.tabClose}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onCloseTab(tab.id);
                                    }}
                                    title="Close tab"
                                    aria-label={`Close ${tab.label} tab`}
                                    data-testid={`close-tab-${tab.testid || tab.id}`}
                                >
                                    ×
                                </span>
                            </button>
                        );
                    })}
                </div>
                {actions && <div className={styles.tabActions}>{actions}</div>}
            </div>}
            <div className={styles.contentArea} data-testid="preview-content">
                {children}
            </div>
        </div>
    );
}
