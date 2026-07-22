import AgentsView from '../../components/agents/AgentsView.jsx';
import AppsView from '../../components/apps/AppsView.jsx';
import ArtifactsHubView from '../../components/artifacts/ArtifactsHubView.jsx';
import HomeAppUnavailable from '../../components/apps/HomeAppUnavailable.jsx';
import RoutinesView from '../../components/routines/RoutinesView.jsx';
import SettingsPage from '../../components/SettingsPage.jsx';
import { useAppSettings } from '../app/AppSettings.jsx';
import { useCustomApps } from '../customApps/CustomApps.jsx';

/** Full desktop pages selected from the sidebar. */
export default function DesktopPages({ view, actions }) {
    const { homeAppSlug } = useAppSettings();
    const customApps = useCustomApps();
    const { catalog } = customApps;

    return (
        <>
            {view === 'settings' && <SettingsPage />}
            {view === 'routines' && <RoutinesView onComposeInChat={actions.composeInNewConversation} />}
            {view === 'agents' && <AgentsView />}
            {view === 'artifacts' && (
                <ArtifactsHubView onOpenConversation={actions.openArtifactInConversation} />
            )}
            {view === 'apps' && customApps.enabled && (
                <AppsView
                    apps={catalog.apps}
                    loading={!catalog.loaded || catalog.loading}
                    error={catalog.error}
                    homeAppSlug={homeAppSlug}
                    onRefresh={catalog.refresh}
                    onOpenApp={actions.expandCustomApp}
                    onOpenAppInDock={actions.openCustomAppInDock}
                />
            )}
            {view === 'home'
                && customApps.enabled
                && homeAppSlug
                && catalog.loaded
                && !catalog.findBySlug(homeAppSlug) && (
                <HomeAppUnavailable
                    message={customApps.error || catalog.error
                        || `No Custom App named “${homeAppSlug}” was found.`}
                    onOpenApps={actions.openCustomApps}
                    onClearHome={actions.clearUnavailableHome}
                />
            )}
        </>
    );
}
