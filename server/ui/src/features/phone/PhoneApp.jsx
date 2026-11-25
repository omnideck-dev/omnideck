import AppStateProviders from '../app/AppStateProviders.jsx';
import SetupGate from '../app/SetupGate.jsx';
import { AppSettingsProvider } from '../app/AppSettings.jsx';
import PhoneShell from './PhoneShell.jsx';
import './phoneTokens.css';

export default function PhoneApp() {
    return (
        <AppSettingsProvider>
            <SetupGate>
                <AppStateProviders>
                    <PhoneShell />
                </AppStateProviders>
            </SetupGate>
        </AppSettingsProvider>
    );
}
