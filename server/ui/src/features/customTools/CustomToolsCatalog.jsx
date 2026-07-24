import { useCallback } from 'react';

import useListPanel from '../../hooks/useListPanel.js';
import { useAppEffectSubscription } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';

/** Loads and mutates the catalog only while its management screen is mounted. */
export function useCustomToolsCatalog() {
    const panel = useListPanel('/api/custom-tools');

    const deleteCustomTool = useCallback((name) => (
        panel.handleDelete(
            name,
            `/api/custom-tools/${encodeURIComponent(name)}`,
            (customTool) => customTool.name !== name,
        )
    ), [panel.handleDelete]);

    const refreshCustomTools = useCallback(() => panel.refetch(), [panel.refetch]);
    useAppEffectSubscription(APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS, refreshCustomTools);

    return {
        customTools: panel.items,
        loading: panel.loading,
        deleting: panel.deleting,
        deleteCustomTool,
        refreshCustomTools,
    };
}
