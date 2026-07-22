import AgentsView from '../../components/agents/AgentsView.jsx';
import AppsView from '../../components/apps/AppsView.jsx';
import ArtifactsHubView from '../../components/artifacts/ArtifactsHubView.jsx';
import HomeAppUnavailable from '../../components/apps/HomeAppUnavailable.jsx';
import RoutinesView from '../../components/routines/RoutinesView.jsx';
import SettingsPage from '../../components/SettingsPage.jsx';

export default function FeatureSurfaces({
    view,
    toolsRefreshSignal,
    composeInNewChat,
    openArtifactInConversation,
    customAppsEnabled,
    customAppsCatalog,
    customApps,
    homeAppSlug,
}) {
    return (
        <>
            {view === 'settings' && <SettingsPage toolsRefreshSignal={toolsRefreshSignal} />}
            {view === 'routines' && <RoutinesView onComposeInChat={composeInNewChat} />}
            {view === 'agents' && <AgentsView />}
            {view === 'artifacts' && (
                <ArtifactsHubView onOpenConversation={openArtifactInConversation} />
            )}
            {view === 'apps' && customAppsEnabled && (
                <AppsView
                    apps={customAppsCatalog.apps}
                    loading={!customAppsCatalog.loaded || customAppsCatalog.loading}
                    error={customAppsCatalog.error}
                    homeAppSlug={homeAppSlug}
                    onRefresh={customAppsCatalog.refresh}
                    onOpenApp={customApps.openFull}
                    onOpenAppBesideChat={customApps.openBesideChat}
                />
            )}
            {view === 'home'
                && customAppsEnabled
                && homeAppSlug
                && customAppsCatalog.loaded
                && !customAppsCatalog.findBySlug(homeAppSlug) && (
                <HomeAppUnavailable
                    message={customApps.error || customAppsCatalog.error
                        || `No Custom App named “${homeAppSlug}” was found.`}
                    onOpenApps={customApps.openApps}
                    onClearHome={customApps.clearUnavailableHome}
                />
            )}
        </>
    );
}
