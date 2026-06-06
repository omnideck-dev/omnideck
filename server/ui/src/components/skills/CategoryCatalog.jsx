import { Fragment, useState } from 'react';

import { categoryIcon } from './skillCategoryIcons.js';
import styles from './CategoryCatalog.module.css';

// A category backed by an integration carries a boolean `connected`; a static
// (built-in) category has `connected: null`.
function isIntegration(category) {
    return category.connected !== null && category.connected !== undefined;
}

export default function CategoryCatalog({ categories }) {
    const [open, setOpen] = useState(() => new Set());

    const toggle = (id) => setOpen((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
    });

    const sorted = [...categories].sort((a, b) => a.label.localeCompare(b.label));

    return (
        <div className={styles.wrap}>
            <table className={styles.table}>
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Kind</th>
                        <th>Status</th>
                        <th className={styles.thNum}>Tools</th>
                        <th aria-hidden="true" />
                    </tr>
                </thead>
                <tbody>
                    {sorted.map((category) => {
                        const integration = isIntegration(category);
                        const isOpen = open.has(category.id);
                        const tools = category.tools || [];
                        return (
                            <Fragment key={category.id}>
                                <tr
                                    className={`${styles.row} ${isOpen ? styles.open : ''}`}
                                    onClick={() => toggle(category.id)}
                                    aria-expanded={isOpen}
                                    data-testid={`cat-row-${category.id}`}
                                >
                                    <td>
                                        <span className={styles.cName}>
                                            <i className={`bi ${categoryIcon(category.id)}`} aria-hidden="true" />
                                            {category.label}
                                        </span>
                                        <span className={styles.cDesc}>{category.description}</span>
                                    </td>
                                    <td>
                                        <span className={`${styles.badge} ${integration ? styles.badgeInfo : styles.badgeNeutral}`}>
                                            {integration ? 'integration' : 'built-in'}
                                        </span>
                                    </td>
                                    <td>
                                        {integration ? (
                                            <span className={styles.statusCell}>
                                                <span className={`${styles.statusDot} ${category.connected ? styles.dotReady : styles.dotIdle}`} />
                                                {category.connected ? 'connected' : 'not connected'}
                                            </span>
                                        ) : (
                                            <span className={styles.statusNone}>—</span>
                                        )}
                                    </td>
                                    <td className={styles.colNum}>{category.tool_count}</td>
                                    <td className={styles.colChev}>
                                        <i className={`bi bi-chevron-right ${styles.chev}`} aria-hidden="true" />
                                    </td>
                                </tr>
                                {isOpen && (
                                    <tr className={styles.toolRow}>
                                        <td colSpan={5}>
                                            <div className={styles.toolBox} data-testid={`cat-tools-${category.id}`}>
                                                {tools.length > 0 ? (
                                                    <div className={styles.toolPills}>
                                                        {tools.map((tool) => <span key={tool} className={styles.toolPill}>{tool}</span>)}
                                                    </div>
                                                ) : (
                                                    <span className={styles.toolEmpty}>No tools available — connect this integration to enable them.</span>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                )}
                            </Fragment>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
