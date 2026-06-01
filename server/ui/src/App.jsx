import React, { useState, useEffect, Suspense } from 'react';

const DesktopApp = React.lazy(() => import('./DesktopApp.jsx'));

function App() {
    const [dark, setDark] = useState(false);

    useEffect(() => {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        setDark(prefersDark);
    }, []);

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    }, [dark]);

    const toggleTheme = () => setDark((d) => !d);

    return (
        <Suspense fallback={null}>
            <DesktopApp dark={dark} onToggleTheme={toggleTheme} />
        </Suspense>
    );
}

export default App;
