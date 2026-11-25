import { createContext, useContext } from 'react';

const FileControlsContext = createContext(null);

export function FileControlsProvider({ controls, children }) {
    return (
        <FileControlsContext.Provider value={controls}>
            {children}
        </FileControlsContext.Provider>
    );
}

export function useFileControls() {
    return useContext(FileControlsContext);
}
