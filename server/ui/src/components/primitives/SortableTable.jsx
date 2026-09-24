import styles from './SortableTable.module.css';

/**
 * Sortable data table — sticky header with click-to-sort columns (a caret marks
 * the active column + direction) and hover/active rows. Presentational: the
 * caller sorts the rows and owns the `sort` state; this renders the chrome and
 * calls `onSort(key)` when a sortable header is clicked.
 *
 * Props:
 *   columns      — [{ key, header, sortable?, render(row), cellClassName?, headerClassName? }]
 *   rows         — already-sorted row objects
 *   rowKey       — (row) => stable key
 *   sort         — { key, dir: 'asc' | 'desc' }
 *   onSort       — (key) => void
 *   onRowClick   — (row) => void (optional)
 *   rowClassName — (row) => string (optional, e.g. a "missing"/dimmed state)
 *   activeRowKey — key of the highlighted row (optional)
 *   rowTestId    — data-testid applied to each row (optional)
 *   testId       — data-testid for the table (optional)
 */
export default function SortableTable({
    columns,
    rows,
    rowKey,
    sort,
    onSort,
    onRowClick,
    rowClassName,
    activeRowKey,
    rowTestId,
    testId,
}) {
    const caret = (key) => (sort?.key === key
        ? <i className={`bi ${sort.dir === 'asc' ? 'bi-caret-up-fill' : 'bi-caret-down-fill'} ${styles.caret}`} />
        : null);

    return (
        <table className={styles.table} data-testid={testId}>
            <thead>
                <tr>
                    {columns.map((col) => (
                        <th
                            key={col.key}
                            className={[col.sortable ? styles.sortable : '', col.headerClassName].filter(Boolean).join(' ')}
                            onClick={col.sortable ? () => onSort?.(col.key) : undefined}
                        >
                            {col.header}{col.sortable ? caret(col.key) : null}
                        </th>
                    ))}
                </tr>
            </thead>
            <tbody>
                {rows.map((row) => {
                    const key = rowKey(row);
                    const active = activeRowKey != null && key === activeRowKey;
                    const cls = [rowClassName?.(row), active ? styles.sel : ''].filter(Boolean).join(' ');
                    return (
                        <tr
                            key={key}
                            className={cls || undefined}
                            onClick={onRowClick ? () => onRowClick(row) : undefined}
                            data-testid={rowTestId}
                        >
                            {columns.map((col) => (
                                <td key={col.key} className={col.cellClassName}>
                                    {col.revealOnHover
                                        ? <span className={styles.onHover}>{col.render(row)}</span>
                                        : col.render(row)}
                                </td>
                            ))}
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}
