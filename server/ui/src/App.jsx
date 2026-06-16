import { useState, useEffect } from 'react';

import DesktopApp from './DesktopApp.jsx';

function App() {
    const [dark, setDark] = useState(false);

    useEffect(() => {
        setDark(window.matchMedia('(prefers-color-scheme: dark)').matches);
    }, []);

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    }, [dark]);

    return <DesktopApp dark={dark} onToggleTheme={() => setDark((d) => !d)} />;
}

export default App;
