import { ConversationCatalogProvider } from '../conversation/catalog/ConversationCatalog.jsx';
import { ConversationSessionProvider } from '../conversation/session/ConversationSession.jsx';
import { WorkspaceProvider } from '../workspace/WorkspaceState.jsx';
import { AgentProvider } from '../agent/AgentState.jsx';
import { CustomAppsProvider } from '../customApps/CustomApps.jsx';
import { AppEffectsProvider } from './AppEffects.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import { GoalsProvider } from '../goals/GoalsState.jsx';
import GoalSessionBridge from '../goals/GoalSessionBridge.jsx';

export default function AppStateProviders({ children }) {
    const { features } = useAppData();
    return (
        <AppEffectsProvider>
            <AgentProvider>
                <WorkspaceProvider>
                    <ConversationCatalogProvider>
                        <GoalsProvider enabled={features.goals === true}>
                            <ConversationSessionProvider>
                                <GoalSessionBridge />
                                <CustomAppsProvider>
                                    {children}
                                </CustomAppsProvider>
                            </ConversationSessionProvider>
                        </GoalsProvider>
                    </ConversationCatalogProvider>
                </WorkspaceProvider>
            </AgentProvider>
        </AppEffectsProvider>
    );
}
