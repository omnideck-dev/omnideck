import SetupWizard from '../../components/SetupWizard.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import { useAppSettings } from './AppSettings.jsx';

/** Holds the setup gate outside the desktop shell. */
export default function AppBootstrap({ children }) {
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
