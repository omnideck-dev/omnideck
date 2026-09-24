import SetupWizard from '../../components/SetupWizard.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import {
    persistFirstRunDesktopLayout,
} from './setupFirstRunDesktopLayout.js';
import { useAppSettings } from './AppSettings.jsx';

/** Shows setup until the application has the state needed to open the desktop. */
export default function SetupGate({ children }) {
    const { profilesHook, providersHook } = useAppData();
    const { setupComplete, finishSetup } = useAppSettings();

    if (setupComplete === null) return null;
    if (setupComplete === false) {
        return (
            <SetupWizard onComplete={(setupResult) => {
                // Write the welcome snapshot before Desktop mounts so startup
                // uses exactly the same restore path as every later refresh.
                persistFirstRunDesktopLayout(setupResult?.welcome);
                finishSetup();
                profilesHook.refresh?.();
                providersHook.refresh?.();
            }} />
        );
    }
    return children;
}
