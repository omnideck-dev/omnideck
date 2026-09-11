import { useMemo, useState } from 'react';

import SearchInput from '../../../components/primitives/SearchInput.jsx';
import styles from './OperationPicker.module.css';

function operationGroups(operations, groups) {
    const validOperations = operations.filter(
        operation => operation && typeof operation.id === 'string',
    );
    const byId = new Map(validOperations.map(operation => [operation.id, operation]));
    const assigned = new Set();
    const result = [];

    for (const group of groups || []) {
        const items = (group.operation_ids || [])
            .map(operationId => byId.get(operationId))
            .filter(operation => operation && !assigned.has(operation.id));
        if (items.length === 0) continue;
        items.forEach(operation => assigned.add(operation.id));
        result.push({ id: group.id, title: group.title, operations: items });
    }

    const ungrouped = validOperations.filter(operation => !assigned.has(operation.id));
    if (ungrouped.length > 0) {
        result.push({
            id: groups?.length ? '__ungrouped__' : '__tools__',
            title: groups?.length ? 'Other tools' : 'Tools',
            operations: ungrouped,
        });
    }
    return result;
}

export default function OperationPicker({
    operations = [],
    groups = [],
    selectedIds,
    onChange,
    disabled = false,
    scrollMode = 'page',
}) {
    const [query, setQuery] = useState('');
    const validOperations = useMemo(
        () => operations.filter(operation => operation && typeof operation.id === 'string'),
        [operations],
    );
    const operationIds = useMemo(
        () => new Set(validOperations.map(operation => operation.id)),
        [validOperations],
    );
    const selected = useMemo(
        () => new Set((selectedIds || []).filter(operationId => operationIds.has(operationId))),
        [operationIds, selectedIds],
    );
    const grouped = useMemo(
        () => operationGroups(validOperations, groups),
        [validOperations, groups],
    );
    const normalizedQuery = query.trim().toLowerCase();
    const visibleGroups = useMemo(() => grouped.map(group => ({
        ...group,
        operations: group.operations.filter(operation => !normalizedQuery
            || String(operation.title || operation.id).toLowerCase().includes(normalizedQuery)
            || String(operation.description || '').toLowerCase().includes(normalizedQuery)),
    })).filter(group => group.operations.length > 0), [grouped, normalizedQuery]);

    const emit = (next) => onChange?.([...next].sort());
    const setOperation = (operationId, enabled) => {
        const next = new Set(selected);
        if (enabled) next.add(operationId);
        else next.delete(operationId);
        emit(next);
    };
    const setGroup = (groupOperations, enabled) => {
        const next = new Set(selected);
        for (const operation of groupOperations) {
            if (enabled) next.add(operation.id);
            else next.delete(operation.id);
        }
        emit(next);
    };

    return (
        <div
            className={`${styles.picker} ${scrollMode === 'contained' ? styles.pickerContained : ''}`}
            data-testid="integration-operation-picker"
        >
            <div className={styles.toolbar}>
                <SearchInput
                    className={styles.search}
                    value={query}
                    onChange={setQuery}
                    placeholder="Search tools"
                    ariaLabel="Search tools"
                    testId="integration-tools-search"
                    clearable={false}
                    disabled={disabled}
                />
                <button
                    type="button"
                    className={styles.bulkButton}
                    onClick={() => emit(new Set(validOperations.map(operation => operation.id)))}
                    disabled={disabled || validOperations.length === 0}
                    data-testid="integration-tools-enable-all"
                >
                    Enable all
                </button>
                <button
                    type="button"
                    className={styles.bulkButton}
                    onClick={() => emit(new Set())}
                    disabled={disabled || selected.size === 0}
                    data-testid="integration-tools-clear"
                >
                    Clear
                </button>
                <span className={styles.total}>
                    {selected.size} of {validOperations.length} enabled
                </span>
            </div>

            <div className={styles.groups}>
                {visibleGroups.map(group => {
                    const selectedCount = group.operations.filter(
                        operation => selected.has(operation.id),
                    ).length;
                    const allSelected = selectedCount === group.operations.length;
                    return (
                        <section className={styles.group} key={group.id}>
                            <button
                                type="button"
                                role="checkbox"
                                aria-checked={allSelected ? true : selectedCount > 0 ? 'mixed' : false}
                                className={styles.groupHeader}
                                onClick={() => setGroup(group.operations, !allSelected)}
                                disabled={disabled}
                                data-testid={`integration-tool-group-${group.id}`}
                            >
                                <span className={`${styles.groupCheck} ${selectedCount > 0 ? styles.groupCheckSelected : ''}`}>
                                    {allSelected ? <i className="bi bi-check-lg" />
                                        : selectedCount > 0 ? <i className="bi bi-dash-lg" /> : null}
                                </span>
                                <span className={styles.groupTitle}>{group.title}</span>
                                <span className={styles.groupCount}>{selectedCount} of {group.operations.length}</span>
                            </button>
                            {group.operations.map(operation => (
                                <label className={styles.operation} key={operation.id}>
                                    <input
                                        type="checkbox"
                                        checked={selected.has(operation.id)}
                                        onChange={event => setOperation(operation.id, event.target.checked)}
                                        disabled={disabled}
                                        data-testid={`integration-tool-${operation.id}`}
                                    />
                                    <span>
                                        <span className={styles.operationTitle}>{operation.title || operation.id}</span>
                                        {operation.description && (
                                            <span className={styles.operationDescription}>{operation.description}</span>
                                        )}
                                    </span>
                                </label>
                            ))}
                        </section>
                    );
                })}
                {visibleGroups.length === 0 && (
                    <div className={styles.noResults}>No tools match “{query}”.</div>
                )}
            </div>
        </div>
    );
}

export { operationGroups };
