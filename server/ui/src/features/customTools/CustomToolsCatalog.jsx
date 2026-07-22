import { createContext, useCallback, useContext, useMemo } from 'react';

import useListPanel from '../../hooks/useListPanel.js';

const CustomToolsCatalogContext = createContext(null);

/** Owns the Custom Tools collection and its server-backed mutations. */
export function CustomToolsCatalogProvider({ children }) {
    const panel = useListPanel('/api/custom-tools');

    const deleteCustomTool = useCallback((name) => (
        panel.handleDelete(
            name,
            `/api/custom-tools/${encodeURIComponent(name)}`,
            (customTool) => customTool.name !== name,
        )
    ), [panel.handleDelete]);

    const refreshCustomTools = useCallback(() => panel.refetch(), [panel.refetch]);
    const value = useMemo(() => ({
        customTools: panel.items,
        loading: panel.loading,
        deleting: panel.deleting,
        deleteCustomTool,
        refreshCustomTools,
    }), [
        deleteCustomTool,
        panel.deleting,
        panel.items,
        panel.loading,
        refreshCustomTools,
    ]);

    return (
        <CustomToolsCatalogContext.Provider value={value}>
            {children}
        </CustomToolsCatalogContext.Provider>
    );
}

export function useCustomToolsCatalog() {
    const value = useContext(CustomToolsCatalogContext);
    if (value === null) {
        throw new Error('useCustomToolsCatalog must be used within CustomToolsCatalogProvider');
    }
    return value;
}
