import AppProviders from './features/app/AppProviders.jsx';
import AppBootstrap from './features/app/AppBootstrap.jsx';
import { AppSettingsProvider } from './features/app/AppSettings.jsx';
import DesktopShell from './features/desktop/DesktopShell.jsx';

export default function DesktopApp() {
    return (
        <AppSettingsProvider>
            <AppBootstrap>
                <AppProviders>
                    <DesktopShell />
                </AppProviders>
            </AppBootstrap>
        </AppSettingsProvider>
    );
}
