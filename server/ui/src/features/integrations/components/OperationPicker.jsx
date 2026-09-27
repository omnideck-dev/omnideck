import { useMemo, useState } from 'react';

import Button from '../../../components/primitives/Button.jsx';
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
    collapsible = false,
    embedded = false,
}) {
    const [query, setQuery] = useState('');
    const [collapsed, setCollapsed] = useState(new Set());
    const [searchCollapsed, setSearchCollapsed] = useState(new Set());
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
            className={`${styles.picker} ${scrollMode === 'contained' ? styles.pickerContained : ''} ${embedded ? styles.pickerEmbedded : ''}`}
            data-testid="integration-operation-picker"
        >
            <div className={styles.toolbar}>
                <SearchInput
                    className={styles.search}
                    value={query}
                    onChange={value => {
                        setQuery(value);
                        // Reveal results for a new query without changing the unfiltered layout.
                        setSearchCollapsed(new Set());
                    }}
                    placeholder="Search tools"
                    ariaLabel="Search tools"
                    testId="integration-tools-search"
                    clearable={false}
                    disabled={disabled}
                />
                <Button
                    type="button"
                    variant="ghost"
                    onClick={() => emit(new Set(validOperations.map(operation => operation.id)))}
                    disabled={disabled || validOperations.length === 0}
                    data-testid="integration-tools-enable-all"
                >
                    Select all
                </Button>
                <Button
                    type="button"
                    variant="ghost"
                    onClick={() => emit(new Set())}
                    disabled={disabled || selected.size === 0}
                    data-testid="integration-tools-clear"
                >
                    Deselect all
                </Button>
                <span className={styles.total}>
                    {selected.size} of {validOperations.length} selected
                </span>
            </div>

            <div className={styles.groups}>
                {visibleGroups.map(group => {
                    const selectedCount = group.operations.filter(
                        operation => selected.has(operation.id),
                    ).length;
                    const allSelected = selectedCount === group.operations.length;
                    const expanded = !collapsible || !(normalizedQuery ? searchCollapsed : collapsed).has(group.id);
                    return (
                        <section className={styles.group} key={group.id}>
                            <div className={styles.groupHeading}>
                            <button
                                type="button"
                                role="checkbox"
                                aria-checked={allSelected ? true : selectedCount > 0 ? 'mixed' : false}
                                className={`${styles.groupHeader} ${collapsible ? styles.groupSelection : ''}`}
                                aria-label={collapsible ? `Select all in ${group.title}` : undefined}
                                onClick={() => setGroup(group.operations, !allSelected)}
                                disabled={disabled}
                                data-testid={`integration-tool-group-${group.id}`}
                            >
                                <span className={`${styles.groupCheck} ${selectedCount > 0 ? styles.groupCheckSelected : ''}`}>
                                    {allSelected ? <i className="bi bi-check-lg" />
                                        : selectedCount > 0 ? <i className="bi bi-dash-lg" /> : null}
                                </span>
                                {!collapsible && <>
                                    <span className={styles.groupTitle}>{group.title}</span>
                                    <span className={styles.groupCount}>{selectedCount} of {group.operations.length}</span>
                                </>}
                            </button>
                            {collapsible && (
                                <button type="button" className={styles.groupToggle} aria-expanded={expanded}
                                    onClick={() => (normalizedQuery ? setSearchCollapsed : setCollapsed)(current => {
                                        const next = new Set(current);
                                        if (next.has(group.id)) next.delete(group.id);
                                        else next.add(group.id);
                                        return next;
                                    })}>
                                    <span className={styles.groupTitle}>{group.title}</span>
                                    <span className={styles.groupCount}>{selectedCount} of {group.operations.length}</span>
                                    <i className={`bi bi-chevron-${expanded ? 'up' : 'down'}`} aria-hidden="true" />
                                </button>
                            )}
                            </div>
                            <div hidden={!expanded}>
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
                            </div>
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
