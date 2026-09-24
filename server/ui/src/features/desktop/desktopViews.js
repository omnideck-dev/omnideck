/**
 * Generic Desktop View contract.
 *
 * Desktop owns the fields it uses for placement and presentation. The
 * `identity` record is deliberately opaque: its owning domain decides which
 * serializable keys are required to resolve the View after a restore.
 */

function isRecord(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/** Validate only the fields understood by the generic Desktop system. */
export function validDesktopView(view) {
    return Boolean(
        isRecord(view)
        && typeof view.id === 'string'
        && view.id.length > 0
        && typeof view.type === 'string'
        && view.type.length > 0
        && typeof view.label === 'string'
        && isRecord(view.identity),
    );
}

function compactRecord(record) {
    return Object.fromEntries(
        Object.entries(record).filter(([, value]) => (
            value !== null && value !== undefined
        )),
    );
}

/**
 * Reduce a runtime View to the durable record Desktop Layout may persist.
 *
 * Domain records, actions, reload signals, and test metadata remain
 * runtime-only. Desktop copies `identity` as an opaque serializable value and
 * leaves validation and rehydration of that value to the domain adapter.
 */
export function persistedDesktopView(view) {
    if (!validDesktopView(view)) return null;
    return {
        ...compactRecord({
            id: view.id,
            type: view.type,
            label: view.label,
            icon: view.icon,
            closable: view.closable,
        }),
        identity: view.identity,
    };
}
