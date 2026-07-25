import FilePreview from '../../components/FilePreview.jsx';
import AgentsView from '../../components/agents/AgentsView.jsx';
import SettingsPage from '../../components/SettingsPage.jsx';
import ArtifactsDesktopView from '../artifacts/ArtifactDesktopAdapter.jsx';
import ConversationDesktopView from '../conversation/ConversationDesktopView.jsx';
import AppsDesktopView from '../customApps/AppsDesktopView.jsx';
import CustomAppDesktopView from '../customApps/CustomAppDesktopAdapter.jsx';
import RoutinesDesktopView from '../routines/RoutinesDesktopView.jsx';
import WorkspaceResourceDesktopView from
    '../workspace/WorkspaceResourceDesktopAdapter.jsx';

/**
 * Maps a serializable View description to its domain-owned Desktop adapter.
 *
 * This router intentionally passes only View identity and placement metadata.
 * Each adapter reads its own domain contexts and translates domain operations
 * into the generic Desktop View command interface.
 */
export default function DesktopViewContent({
    view,
    active,
    tabGroupId,
}) {
    if (view.type === 'custom-app') {
        return (
            <CustomAppDesktopView
                view={view}
                active={active}
            />
        );
    }

    if (view.type === 'workspace-resource') {
        return <WorkspaceResourceDesktopView view={view} active={active} />;
    }

    if (view.type === 'artifact-file') {
        return <FilePreview item={view.artifact} />;
    }

    if (view.type === 'conversation') {
        return (
            <ConversationDesktopView
                view={view}
                tabGroupId={tabGroupId}
            />
        );
    }

    // Page-like views are statically known today. Keeping this switch explicit
    // makes the supported View types visible without introducing a premature
    // runtime registration system.
    if (view.type === 'settings') return <SettingsPage />;
    if (view.type === 'agents') return <AgentsView />;
    if (view.type === 'routines') return <RoutinesDesktopView />;
    if (view.type === 'artifacts') {
        return <ArtifactsDesktopView view={view} tabGroupId={tabGroupId} />;
    }
    if (view.type === 'apps') {
        return <AppsDesktopView tabGroupId={tabGroupId} />;
    }
    return null;
}
