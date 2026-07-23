import { ConversationCatalogProvider } from '../conversation/catalog/ConversationCatalog.jsx';
import { ConversationSessionProvider } from '../conversation/session/ConversationSession.jsx';
import { DesktopNavigationProvider } from '../navigation/DesktopNavigation.jsx';
import { WorkspaceProvider } from '../workspace/WorkspaceState.jsx';
import { AgentProvider } from '../agent/AgentState.jsx';
import { CustomToolsCatalogProvider } from '../customTools/CustomToolsCatalog.jsx';
import { CustomAppsProvider } from '../customApps/CustomApps.jsx';

export default function AppStateProviders({ children }) {
    return (
        <AgentProvider>
            <WorkspaceProvider>
                <ConversationCatalogProvider>
                    <CustomToolsCatalogProvider>
                        <ConversationSessionProvider>
                            <DesktopNavigationProvider>
                                <CustomAppsProvider>
                                    {children}
                                </CustomAppsProvider>
                            </DesktopNavigationProvider>
                        </ConversationSessionProvider>
                    </CustomToolsCatalogProvider>
                </ConversationCatalogProvider>
            </WorkspaceProvider>
        </AgentProvider>
    );
}
