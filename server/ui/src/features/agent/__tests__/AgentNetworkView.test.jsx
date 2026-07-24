import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AgentProvider, useAgentDispatch } from '../AgentState.jsx';
import {
    WorkspaceProvider,
    useWorkspaceDispatch,
} from '../../workspace/WorkspaceState.jsx';
import AgentNetworkView from '../AgentNetworkView.jsx';

vi.mock('../../../components/AgentNetwork.jsx', () => ({
    default: ({ onSelectAgent }) => (
        <div data-testid="agent-network">
            <button onClick={() => onSelectAgent('child-1')}>Select child</button>
        </div>
    ),
}));

vi.mock('../../../components/AgentActivityView.jsx', () => ({
    default: ({ agentId, availableViews, onOpenView }) => (
        <div data-testid="agent-activity-view">
            {agentId}
            {availableViews.map((view) => (
                <button key={view} onClick={() => onOpenView(view)}>{view}</button>
            ))}
        </div>
    ),
}));

function renderView(props = {}) {
    let dispatch;
    let workspaceDispatch;
    const defaults = {
        selectedAgentId: null,
        agentCounts: { total: 2, running: 1, complete: 1, error: 0 },
        onClose: vi.fn(),
        onOpenOverview: vi.fn(),
        onSelectAgent: vi.fn(),
        onNudge: vi.fn(),
        onPreview: vi.fn(),
    };
    const viewProps = { ...defaults, ...props };

    function Harness() {
        dispatch = useAgentDispatch();
        workspaceDispatch = useWorkspaceDispatch();
        return <AgentNetworkView {...viewProps} />;
    }

    render(
        <AgentProvider>
            <WorkspaceProvider>
                <Harness />
            </WorkspaceProvider>
        </AgentProvider>,
    );

    const startAgent = (agentId, parentAgentId, name) => {
        act(() => {
            dispatch({
                type: 'AGENT_STARTED',
                agentId,
                agentName: name,
                parentAgentId,
                instruction: '',
                timestamp: Date.now(),
            });
            workspaceDispatch({
                type: 'WORKSPACE_AGENT_STARTED',
                agentId,
                parentAgentId,
            });
        });
    };

    return {
        ...viewProps,
        startAgent,
        updateWorkspace: (action) => act(() => workspaceDispatch(action)),
    };
}

describe('AgentNetworkView', () => {
    it('owns the shared feature header and graph overview', () => {
        const { onClose, onSelectAgent } = renderView();

        expect(screen.getByRole('heading', { name: 'Agent Network' })).toBeInTheDocument();
        expect(screen.getByText('2 agents')).toBeInTheDocument();
        expect(screen.getByText('running')).toBeInTheDocument();
        expect(screen.getByTestId('agent-network')).toBeInTheDocument();

        fireEvent.click(screen.getByTestId('back-btn-chat'));
        expect(onClose).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByText('Select child'));
        expect(onSelectAgent).toHaveBeenCalledWith('child-1');
    });

    it('owns activity subnavigation and agent breadcrumbs', () => {
        const onOpenOverview = vi.fn();
        const onSelectAgent = vi.fn();
        const { startAgent } = renderView({
            selectedAgentId: 'child-1',
            onOpenOverview,
            onSelectAgent,
        });
        startAgent('root-1', null, 'omnideck');
        startAgent('child-1', 'root-1', 'research_agent');

        expect(screen.getByTestId('agent-activity-view')).toHaveTextContent('child-1');
        expect(screen.getByText('Research Agent')).toBeInTheDocument();

        fireEvent.click(screen.getByTestId('back-btn-agents'));
        expect(onOpenOverview).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByRole('button', { name: 'Omnideck' }));
        expect(onSelectAgent).toHaveBeenCalledWith('root-1');
    });

    it('offers available Browser and Terminal views for the selected agent', () => {
        const onOpenExecutionView = vi.fn();
        const { startAgent, updateWorkspace } = renderView({
            selectedAgentId: 'child-1',
            onOpenExecutionView,
        });
        startAgent('root-1', null, 'omnideck');
        startAgent('child-1', 'root-1', 'research_agent');
        updateWorkspace({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'child-1',
            snapshot: {
                url: 'https://example.test',
                title: 'Example',
                screenshot: 'image-data',
                tabId: 1,
                openTabIds: [1],
                agentId: 'child-1',
            },
        });
        updateWorkspace({
            type: 'UPDATE_TERMINAL',
            agentId: 'child-1',
            event: {
                cmd_id: 'command-1',
                cmd: 'pwd',
                status: 'complete',
                agentId: 'child-1',
            },
        });

        fireEvent.click(screen.getByRole('button', { name: 'browser' }));
        fireEvent.click(screen.getByRole('button', { name: 'terminal' }));
        expect(onOpenExecutionView).toHaveBeenNthCalledWith(
            1,
            'child-1',
            'browser',
        );
        expect(onOpenExecutionView).toHaveBeenNthCalledWith(
            2,
            'child-1',
            'terminal',
        );
    });
});
