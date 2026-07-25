import BrowserPreview from '../../components/BrowserPreview.jsx';
import TerminalPanel from '../../components/TerminalOutput.jsx';
import { useWorkspaceState } from './WorkspaceState.jsx';

function sortedBrowserTabs(browserTabs) {
    return Object.entries(browserTabs || {})
        .map(([key, snapshot]) => ({ id: Number(key), snapshot }))
        .sort((left, right) => left.id - right.id);
}

/**
 * Renders one resource owned by one explicit agent.
 *
 * Placement never changes the agent lookup; moving this view only changes
 * where the same workspace resource is rendered.
 */
export default function WorkspaceResourceView({
    agentId,
    resourceId,
    browser,
}) {
    const workspace = useWorkspaceState().byAgentId[agentId];
    if (!workspace) return null;

    const browserTabsList = sortedBrowserTabs(workspace.browserTabs);
    if (resourceId === 'browser' && browserTabsList.length > 0) {
        const ownsBrowserSession = browser.agentId === agentId;
        const selectedId = ownsBrowserSession
            ? browser.selectedTabId
            : browserTabsList[0].id;
        return (
            <BrowserPreview
                tabs={ownsBrowserSession ? browser.tabs : browserTabsList}
                selectedId={selectedId}
                onSelectTab={ownsBrowserSession ? browser.setSelectedTabId : undefined}
                control={ownsBrowserSession ? browser.control : undefined}
                inputActive={ownsBrowserSession}
            />
        );
    }
    if (resourceId === 'terminal' && workspace.terminalLines.length > 0) {
        return <TerminalPanel lines={workspace.terminalLines} />;
    }
    return null;
}
