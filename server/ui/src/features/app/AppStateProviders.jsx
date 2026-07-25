import { ConversationCatalogProvider } from '../conversation/catalog/ConversationCatalog.jsx';
import { ConversationSessionProvider } from '../conversation/session/ConversationSession.jsx';
import { WorkspaceProvider } from '../workspace/WorkspaceState.jsx';
import { AgentProvider } from '../agent/AgentState.jsx';
import { CustomAppsProvider } from '../customApps/CustomApps.jsx';
import { AppEffectsProvider } from './AppEffects.jsx';

export default function AppStateProviders({ children }) {
    return (
        <AppEffectsProvider>
            <AgentProvider>
                <WorkspaceProvider>
                    <ConversationCatalogProvider>
                        <ConversationSessionProvider>
                            <CustomAppsProvider>
                                {children}
                            </CustomAppsProvider>
                        </ConversationSessionProvider>
                    </ConversationCatalogProvider>
                </WorkspaceProvider>
            </AgentProvider>
        </AppEffectsProvider>
    );
}
