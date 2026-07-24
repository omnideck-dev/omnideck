import AgentExecutionView from '../workspace/AgentExecutionView.jsx';
import FilePreview from '../../components/FilePreview.jsx';
import CustomAppSurface from './CustomAppSurface.jsx';
import DesktopPages from './DesktopPages.jsx';
import MainSurface from './MainSurface.jsx';

/** Maps a serializable surface description to its feature-owned renderer. */
export default function DesktopSurfaceContent({
    surface,
    active,
    paneId,
    workspace,
    agentCounts,
    session,
    selectedProfileId,
    profileRevision,
    actions,
}) {
    if (surface.kind === 'custom-app') {
        return (
            <CustomAppSurface
                surface={surface}
                active={active}
                actions={actions.customApp}
            />
        );
    }

    if (surface.kind === 'conversation-execution') {
        return (
            <AgentExecutionView
                agentId={surface.agentId}
                resourceId={surface.resourceId}
                browser={workspace.browser}
            />
        );
    }

    if (surface.kind === 'artifact-file') {
        return <FilePreview item={surface.artifact} />;
    }

    if (surface.kind === 'conversation') {
        return (
            <MainSurface
                view={surface.destination?.kind || 'chat'}
                paneId={paneId}
                selectedAgentId={surface.destination?.agentId || null}
                agentCounts={agentCounts}
                session={session}
                selectedProfileId={selectedProfileId}
                profileRevision={profileRevision}
                actions={actions.main}
            />
        );
    }

    return (
        <DesktopPages
            surface={surface}
            paneId={paneId}
            actions={actions.pages}
        />
    );
}
