import styles from './SplitPanel.module.css';

/**
 * Master-detail container following the SIGNAL Split Panel pattern.
 * Owns outer gutters, spaced panes, a divider, and independent desktop scrolling.
 * Narrow screens use stacked document flow instead of two scroll panes.
 */
export default function SplitPanel({ children, className = '' }) {
    return <div className={`${styles.container} ${className}`}>{children}</div>;
}

SplitPanel.List = function SplitPanelList({ children, className = '' }) {
    return <div className={`${styles.list} ${className}`}>{children}</div>;
};

SplitPanel.Detail = function SplitPanelDetail({ children, className = '' }) {
    return <div className={`${styles.detail} ${className}`}>{children}</div>;
};

SplitPanel.Header = function SplitPanelHeader({ children, actions }) {
    return <div className={styles.header}><span>{children}</span>{actions}</div>;
};
