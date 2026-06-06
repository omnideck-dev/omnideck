import SearchInput from './SearchInput.jsx';
import styles from './LibraryHeader.module.css';

/**
 * SIGNAL §27 Library Header: a secondary, in-content view switch with scoped search.
 *
 * View tabs sit flush-left and drive the body below; a scoped search aligns right.
 * Deliberately distinct from the brand Tabs (§14) — body font, mixed-case, count
 * badge — so it reads as subordinate to the uppercase Settings tabs above it.
 *
 * Label-agnostic: the caller supplies the views, the active one, the search
 * placeholder (which it swaps to match the active view), and an optional `actions`
 * slot for an affordance like "+ New" that only an editable view carries.
 *
 * Props:
 *   views          — [{ id, label, count }]
 *   activeView     — id of the active view
 *   onViewChange   — (id) => void
 *   searchValue    — controlled search text
 *   onSearchChange — (value) => void
 *   searchPlaceholder — placeholder for the active view
 *   actions        — optional node rendered right of the search
 */
export default function LibraryHeader({
    views,
    activeView,
    onViewChange,
    searchValue,
    onSearchChange,
    searchPlaceholder,
    actions,
}) {
    return (
        <div className={styles.header}>
            <div className={styles.views} role="tablist">
                {views.map((view) => {
                    const active = view.id === activeView;
                    return (
                        <button
                            key={view.id}
                            type="button"
                            role="tab"
                            aria-selected={active}
                            className={[styles.tab, active ? styles.active : ''].filter(Boolean).join(' ')}
                            onClick={() => onViewChange(view.id)}
                        >
                            {view.label}
                            <span className={styles.count}>{view.count}</span>
                        </button>
                    );
                })}
            </div>
            <div className={styles.right}>
                <SearchInput
                    className={styles.searchBox}
                    value={searchValue}
                    onChange={onSearchChange}
                    placeholder={searchPlaceholder}
                />
                {actions}
            </div>
        </div>
    );
}
