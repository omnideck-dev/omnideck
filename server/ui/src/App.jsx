import AppStateProviders from './features/app/AppStateProviders.jsx';
import SetupGate from './features/app/SetupGate.jsx';
import { AppSettingsProvider } from './features/app/AppSettings.jsx';
import { OmnideckHostProvider } from './features/app/OmnideckHost.jsx';
import Desktop from './features/desktop/Desktop.jsx';

export default function App() {
    return (
        <OmnideckHostProvider>
            <AppSettingsProvider>
                <SetupGate>
                    <AppStateProviders>
                        <Desktop />
                    </AppStateProviders>
                </SetupGate>
            </AppSettingsProvider>
        </OmnideckHostProvider>
    );
}
