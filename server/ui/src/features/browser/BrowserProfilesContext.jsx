import { createContext, useContext } from 'react';

const BrowserProfilesContext = createContext(null);

export function BrowserProfilesCatalogProvider({ value, children }) {
    return (
        <BrowserProfilesContext.Provider value={value}>
            {children}
        </BrowserProfilesContext.Provider>
    );
}

export function useBrowserProfilesCatalog() {
    const value = useContext(BrowserProfilesContext);
    if (value === null) {
        throw new Error(
            'useBrowserProfilesCatalog must be used inside <AppDataProvider>',
        );
    }
    return value;
}
