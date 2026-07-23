import SetupWizard from '../../components/SetupWizard.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import { useAppSettings } from './AppSettings.jsx';

/** Shows setup until the application has the state needed to open the desktop. */
export default function SetupGate({ children }) {
    const { profilesHook } = useAppData();
    const { setupComplete, finishSetup } = useAppSettings();

    if (setupComplete === null) return null;
    if (setupComplete === false) {
        return (
            <SetupWizard onComplete={() => {
                finishSetup();
                profilesHook.refresh?.();
            }} />
        );
    }
    return children;
}
