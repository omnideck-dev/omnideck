import AgentsView from '../../components/agents/AgentsView.jsx';
import { useDesktopNavigationCommands } from '../navigation/DesktopNavigation.jsx';
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
    const { openSettings } = useDesktopNavigationCommands();
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
        const target = view.identity?.navigationTarget;
        return <SettingsView initialTab={target?.tab || 'skills'} initialConnectionId={target?.connectionId} initialSkillId={target?.skillId} selectionRequest={target} />;
    }
    if (view.type === 'browser') return <BrowserView />;
    if (view.type === 'agents') return <AgentsView
        onOpenIntegration={connectionId => openSettings('integrations', { connectionId })}
        onOpenSkill={skillId => openSettings('skills', { skillId })} />;
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
