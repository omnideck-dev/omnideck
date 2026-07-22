import { ConversationCatalogProvider } from '../conversation/catalog/ConversationCatalog.jsx';
import { ConversationSessionProvider } from '../conversation/session/ConversationSession.jsx';
import { DesktopNavigationProvider } from '../navigation/DesktopNavigation.jsx';
import { WorkspaceProvider } from '../workspace/WorkspaceState.jsx';
import { AgentProvider } from '../agent/AgentState.jsx';

export default function AppProviders({ children }) {
    return (
        <AgentProvider>
            <WorkspaceProvider>
                <ConversationCatalogProvider>
                    <ConversationSessionProvider>
                        <DesktopNavigationProvider>
                            {children}
                        </DesktopNavigationProvider>
                    </ConversationSessionProvider>
                </ConversationCatalogProvider>
            </WorkspaceProvider>
        </AgentProvider>
    );
}
