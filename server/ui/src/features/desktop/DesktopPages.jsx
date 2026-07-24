import AgentsView from '../../components/agents/AgentsView.jsx';
import AppsView from '../../components/apps/AppsView.jsx';
import ArtifactsHubView from '../../components/artifacts/ArtifactsHubView.jsx';
import RoutinesView from '../../components/routines/RoutinesView.jsx';
import SettingsPage from '../../components/SettingsPage.jsx';
import { useCustomApps } from '../customApps/CustomApps.jsx';

/** Full desktop pages selected from the sidebar. */
export default function DesktopPages({ surface, paneId, actions }) {
    const view = surface.kind;
    const customApps = useCustomApps();
    const { catalog } = customApps;

    return (
        <>
            {view === 'settings' && <SettingsPage />}
            {view === 'routines' && <RoutinesView onComposeInChat={actions.composeInNewConversation} />}
            {view === 'agents' && <AgentsView />}
            {view === 'artifacts' && (
                <ArtifactsHubView
                    conversationId={surface.destination?.conversationId || null}
                    onOpenArtifact={(artifact) => actions.openArtifact(artifact, paneId)}
                />
            )}
            {view === 'apps' && customApps.enabled && (
                <AppsView
                    apps={catalog.apps}
                    loading={!catalog.loaded || catalog.loading}
                    error={catalog.error}
                    onRefresh={catalog.refresh}
                    onOpenApp={(app) => actions.openApp(app, paneId)}
                />
            )}
        </>
    );
}
