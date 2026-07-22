import AppProviders from './features/app/AppProviders.jsx';
import DesktopShell from './features/desktop/DesktopShell.jsx';

export default function DesktopApp() {
    return (
        <AppProviders>
            <DesktopShell />
        </AppProviders>
    );
}
