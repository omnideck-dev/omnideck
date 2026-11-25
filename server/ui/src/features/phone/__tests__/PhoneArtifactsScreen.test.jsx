import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const artifacts = vi.hoisted(() => ({ items: [], loading: false, calls: [] }));
vi.mock('../../../hooks/useArtifacts.js', () => ({
    default: (options) => {
        artifacts.calls.push(options);
        return { items: artifacts.items, loading: artifacts.loading };
    },
}));

const { default: PhoneArtifactsScreen } = await import('../PhoneArtifactsScreen.jsx');

const REPORT = { id: 'a1', filename: 'Pricing.md', content_type: 'text/markdown', conversation_title: 'Pricing for project tools', created_at: '2026-11-24T10:00:00Z' };
const SHEET = { id: 'a2', filename: 'Venues.xlsx', content_type: 'application/octet-stream', conversation_title: null, created_at: '2026-11-20T10:00:00Z' };
const GONE = { id: 'a3', filename: 'Old.md', content_type: 'text/markdown', status: 'missing', conversation_title: 'Old chat', created_at: '2026-11-01T10:00:00Z' };

function setup(props = {}) {
    const handlers = { onBack: vi.fn(), onClearConversation: vi.fn(), onOpenArtifact: vi.fn() };
    render(<PhoneArtifactsScreen backLabel="Chats" {...handlers} {...props} />);
    return handlers;
}

describe('PhoneArtifactsScreen', () => {
    it('lists every artifact newest first with its chat', () => {
        artifacts.items = [SHEET, REPORT];
        setup();
        const rows = screen.getAllByTestId('phone-artifact');
        expect(rows.map((row) => row.textContent)).toEqual([
            expect.stringContaining('Pricing.md'),
            expect.stringContaining('Venues.xlsx'),
        ]);
        expect(rows[0]).toHaveTextContent('Pricing for project tools');
        expect(rows[1]).toHaveTextContent('Conversation deleted');
        expect(screen.getByTestId('phone-title')).toHaveTextContent('Artifacts');
        expect(artifacts.calls.at(-1)).toEqual({ conversationId: undefined });
    });

    it('filters by file name and says when nothing matches', async () => {
        const user = userEvent.setup();
        artifacts.items = [SHEET, REPORT];
        setup();
        await user.type(screen.getByTestId('phone-artifacts-search'), 'venue');
        expect(screen.getAllByTestId('phone-artifact')).toHaveLength(1);
        await user.type(screen.getByTestId('phone-artifacts-search'), 'zzz');
        expect(screen.getByTestId('phone-artifacts-empty')).toHaveTextContent('No artifacts match your search.');
    });

    it('opens an artifact and keeps missing files closed', async () => {
        const user = userEvent.setup();
        artifacts.items = [REPORT, GONE];
        const { onOpenArtifact } = setup();
        await user.click(screen.getByText('Pricing.md'));
        expect(onOpenArtifact).toHaveBeenCalledWith(REPORT);
        expect(screen.getByText('Old.md').closest('button')).toBeDisabled();
        expect(screen.getByText('File missing')).toBeInTheDocument();
    });

    it('scopes to one chat and clears the filter', async () => {
        const user = userEvent.setup();
        artifacts.items = [REPORT];
        const { onClearConversation } = setup({ conversationId: 'c1', conversationTitle: 'Pricing for project tools' });
        expect(screen.getByTestId('phone-title')).toHaveTextContent('Conversation artifacts');
        expect(artifacts.calls.at(-1)).toEqual({ conversationId: 'c1' });
        await user.click(screen.getByTestId('phone-artifacts-clear-filter'));
        expect(onClearConversation).toHaveBeenCalledOnce();
    });

    it('says when there are no artifacts yet', () => {
        artifacts.items = [];
        setup();
        expect(screen.getByTestId('phone-artifacts-empty')).toHaveTextContent('No artifacts yet.');
    });
});
