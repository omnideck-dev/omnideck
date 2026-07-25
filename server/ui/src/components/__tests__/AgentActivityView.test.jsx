import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { AgentProvider, useAgentDispatch } from '../../features/agent/AgentState.jsx';
import AgentActivityView from '../AgentActivityView.jsx';
import { act, useState } from 'react';

// ── Helpers ──────────────────────────────────────────────────────────

function renderView(props = {}) {
    let dispatch;

    function Harness() {
        const [agentId, setAgentId] = useState(props.agentId ?? 'a1');
        dispatch = useAgentDispatch();
        return (
            <AgentActivityView
                agentId={agentId}
                onBack={() => setAgentId(null)}
                onSelectAgent={setAgentId}
                onNudge={vi.fn()}
                onPreview={vi.fn()}
                {...props}
            />
        );
    }

    const result = render(
        <AgentProvider>
            <Harness />
        </AgentProvider>,
    );

    return {
        dispatch: (action) => act(() => dispatch(action)),
        ...result,
    };
}

function startAgent(dispatch, id, { name = 'omnideck', parent = null, instruction = '' } = {}) {
    dispatch({
        type: 'AGENT_STARTED',
        agentId: id,
        agentName: name,
        parentAgentId: parent,
        instruction,
        timestamp: Date.now(),
    });
}

// ─────────────────────────────────────────────────────────────────────

describe('AgentActivityView', () => {
    it('renders nothing when no agent is selected', () => {
        const { container } = render(
            <AgentProvider>
                <AgentActivityView onNudge={vi.fn()} onPreview={vi.fn()} />
            </AgentProvider>,
        );
        expect(container.innerHTML).toBe('');
    });

    it('renders agent name and instruction', () => {
        const { dispatch } = renderView();
        startAgent(dispatch, 'a1', { instruction: 'Go to example.com' });

        expect(screen.getByText('Omnideck')).toBeInTheDocument();
        expect(screen.getByText('Go to example.com')).toBeInTheDocument();
    });

    describe('activity pane', () => {
        it('keeps following text as streamed chunks merge into one activity entry', () => {
            const { dispatch } = renderView();
            startAgent(dispatch, 'a1');
            dispatch({
                type: 'APPEND_STREAM_CHUNK',
                agentId: 'a1',
                content: 'first',
                thinking: '',
            });

            const activity = screen.getByTestId('agent-activity-scroll');
            Object.defineProperty(activity, 'scrollHeight', {
                configurable: true,
                value: 500,
            });
            activity.scrollTop = 0;

            // This extends the existing content entry, so activityLog.length
            // remains unchanged. Content growth must still trigger scrolling.
            dispatch({
                type: 'APPEND_STREAM_CHUNK',
                agentId: 'a1',
                content: ' second',
                thinking: '',
            });

            expect(activity.scrollTop).toBe(500);
        });

    });

    describe('nudge bar', () => {
        it('is disabled after stop is requested', () => {
            const { dispatch } = renderView({ nudgeDisabled: true });
            startAgent(dispatch, 'a1');

            expect(screen.getByPlaceholderText('Stopping...')).toBeDisabled();
        });
    });

    describe('agent workspace resources', () => {
        it('renders only the concrete available actions and opens them explicitly', async () => {
            const user = userEvent.setup();
            const onOpenView = vi.fn();
            const { dispatch } = renderView({
                availableViews: ['browser', 'terminal'],
                onOpenView,
            });
            startAgent(dispatch, 'a1');

            await user.click(screen.getByRole('button', { name: 'Browser' }));
            await user.click(screen.getByRole('button', { name: 'Terminal' }));

            expect(onOpenView).toHaveBeenNthCalledWith(1, 'browser');
            expect(onOpenView).toHaveBeenNthCalledWith(2, 'terminal');
        });

        it('does not render a resource action when it is unavailable', () => {
            const { dispatch } = renderView({ availableViews: ['browser'] });
            startAgent(dispatch, 'a1');

            expect(screen.getByRole('button', { name: 'Browser' })).toBeInTheDocument();
            expect(screen.queryByRole('button', { name: 'Terminal' })).not.toBeInTheDocument();
        });
    });

    describe('file outputs in activity stream', () => {
        it('renders file outputs via AgentOutput when showFileOutputs is true', () => {
            const { dispatch } = renderView();
            startAgent(dispatch, 'a1');
            dispatch({
                type: 'APPEND_ACTIVITY',
                agentId: 'a1',
                entry: { type: 'file_output', filename: 'report.html', content_type: 'text/html', content: 'abc' },
            });

            expect(screen.getByText('report.html')).toBeInTheDocument();
        });
    });

    describe('spawn card', () => {
        function spawnChildren(dispatch) {
            startAgent(dispatch, 'a1');
            dispatch({
                type: 'APPEND_ACTIVITY',
                agentId: 'a1',
                entry: { type: 'spawn_requested', correlationId: 'c-1' },
            });
            dispatch({
                type: 'APPEND_ACTIVITY',
                agentId: 'a1',
                entry: { type: 'spawn_requested', correlationId: 'c-2' },
            });
            dispatch({
                type: 'AGENT_STARTED', agentId: 'c1', agentName: 'research_agent',
                parentAgentId: 'a1', instruction: '', correlationId: 'c-1', timestamp: Date.now(),
            });
            dispatch({
                type: 'AGENT_STARTED', agentId: 'c2', agentName: 'code_expert',
                parentAgentId: 'a1', instruction: '', correlationId: 'c-2', timestamp: Date.now(),
            });
        }

        it('renders an inline spawn card for the agent\'s sub-agents', () => {
            const { dispatch } = renderView();
            spawnChildren(dispatch);

            expect(screen.getByTestId('spawn-card')).toBeInTheDocument();
            expect(screen.getAllByTestId('spawn-card-row')).toHaveLength(2);
        });

        it('clicking a spawn card row switches the view to that sub-agent', () => {
            const { dispatch } = renderView();
            spawnChildren(dispatch);

            act(() => {
                screen.getAllByTestId('spawn-card-row')[0].click();
            });
            expect(screen.getByTestId('agent-activity-title')).toHaveTextContent('Research Agent');
        });

        it('renders no spawn card when the agent spawned nothing', () => {
            const { dispatch } = renderView();
            startAgent(dispatch, 'a1');
            expect(screen.queryByTestId('spawn-card')).not.toBeInTheDocument();
        });
    });

describe('collapsible instruction', () => {
        it('starts collapsed — body is hidden, preview shows the first line', () => {
            const { dispatch } = renderView();
            startAgent(dispatch, 'a1', {
                instruction: 'First line summary\n\nLonger detail that should only appear when expanded.',
            });

            // Toggle visible, body hidden
            expect(screen.getByTestId('instruction-toggle')).toBeInTheDocument();
            expect(screen.queryByTestId('instruction-body')).not.toBeInTheDocument();

            // Preview shows the first line
            expect(screen.getByTestId('instruction-toggle')).toHaveTextContent('First line summary');
            // Longer detail isn't visible when collapsed
            expect(screen.queryByText(/Longer detail/)).not.toBeInTheDocument();
        });

        it('clicking the toggle expands the full instruction body', async () => {
            const user = userEvent.setup();
            const { dispatch } = renderView();
            startAgent(dispatch, 'a1', {
                instruction: 'First line\n\nFull detail here.',
            });

            await user.click(screen.getByTestId('instruction-toggle'));
            const body = screen.getByTestId('instruction-body');
            expect(body).toHaveTextContent('First line');
            expect(body).toHaveTextContent('Full detail here.');

            // Toggling again collapses
            await user.click(screen.getByTestId('instruction-toggle'));
            expect(screen.queryByTestId('instruction-body')).not.toBeInTheDocument();
        });

        it('does not render the instruction bar when there is no instruction', () => {
            const { dispatch } = renderView();
            startAgent(dispatch, 'a1', { instruction: '' });
            expect(screen.queryByTestId('instruction-toggle')).not.toBeInTheDocument();
        });
    });
});
