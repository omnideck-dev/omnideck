import { createContext, useContext, useEffect, useMemo, useState } from 'react';

/**
 * App-wide light/dark theme. Owns the single source of truth (a boolean),
 * mirrors it onto the ``data-theme`` attribute on <html> for the CSS layer,
 * and hands both the flag and a toggle to any component that needs the theme
 * in JS (the nav toggle, the code editor) without prop-drilling.
 */
const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
    const [dark, setDark] = useState(false);

    // Seed from the OS preference on mount. Guarded because jsdom (tests) and
    // older environments don't implement matchMedia.
    useEffect(() => {
        const mql = window.matchMedia?.('(prefers-color-scheme: dark)');
        if (mql) setDark(mql.matches);
    }, []);

    // The CSS layer keys everything off this attribute, so it stays the mirror
    // of our state rather than a second source of truth.
    useEffect(() => {
        document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    }, [dark]);

    const value = useMemo(
        () => ({ dark, toggleTheme: () => setDark((d) => !d) }),
        [dark],
    );
    return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** Returns ``{dark, toggleTheme}``. Throws if used outside the provider. */
export function useTheme() {
    const value = useContext(ThemeContext);
    if (value === null) {
        throw new Error('useTheme must be used inside <ThemeProvider>');
    }
    return value;
}
