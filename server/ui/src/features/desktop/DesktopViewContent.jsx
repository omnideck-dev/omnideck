import AgentsView from '../../components/agents/AgentsView.jsx';
import SettingsView from '../../components/SettingsView.jsx';
import ArtifactsHubDesktopView, {
    ArtifactFileDesktopView,
} from '../artifacts/ArtifactDesktopAdapter.jsx';
import ConversationDesktopView from '../conversation/ConversationDesktopView.jsx';
import AppsDesktopView from '../customApps/AppsDesktopView.jsx';
import BrowserView from '../browser/BrowserView.jsx';
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
    visible,
    tabGroupId,
}) {
    if (view.type === 'custom-app') {
        return (
            <CustomAppDesktopView
                view={view}
                visible={visible}
            />
        );
    }

    if (view.type === 'workspace-resource') {
        return (
            <WorkspaceResourceDesktopView
                view={view}
                visible={visible}
            />
        );
    }

    if (view.type === 'artifact-file') {
        return <ArtifactFileDesktopView view={view} />;
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
    if (view.type === 'settings') {
        return <SettingsView initialTab={view.identity?.navigationTarget?.tab || 'skills'} />;
    }
    if (view.type === 'browser') return <BrowserView />;
    if (view.type === 'agents') return <AgentsView />;
    if (view.type === 'routines') return <RoutinesDesktopView />;
    if (view.type === 'artifacts') {
        return (
            <ArtifactsHubDesktopView
                view={view}
                visible={visible}
                tabGroupId={tabGroupId}
            />
        );
    }
    if (view.type === 'apps') {
        return <AppsDesktopView tabGroupId={tabGroupId} />;
    }
    return null;
}
