import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ConversationDetails from '../ConversationDetails.jsx';
import { buildConversationDetails } from '../conversationDetailsModel.js';

const input = { conversationId: 'conv', rootId: 'r', agents: { r: { id: 'r', parentId: null, name: 'Primary' } }, workspace: { r: { terminalLines: [{ cmd: 'true' }] } } };
const model = () => buildConversationDetails(input);
beforeEach(() => localStorage.clear());

describe('Details disclosure', () => {
    it('groups workspace items by type and routes each owner to its own resource', () => {
        const data = buildConversationDetails({ ...input, agents: {
            ...input.agents,
            c: { id: 'c', parentId: 'r', name: 'Analyst', status: 'success' },
        }, workspace: {
            ...input.workspace,
            c: { terminalLines: [{ cmd: 'ls' }], browserTabs: { 1: { screenshot: 'png' } } },
        } });
        const onSelect = vi.fn();
        render(<ConversationDetails conversationId="conv" model={data} onSelect={onSelect} />);
        fireEvent.click(screen.getByRole('button', { name: /Details/ }));
        const terminals = screen.getByRole('region', { name: 'Terminals' });
        expect(within(terminals).getAllByRole('button')).toHaveLength(2);
        expect(within(terminals).getByText('Primary agent')).toBeVisible();
        expect(within(terminals).getByText('Analyst')).toBeVisible();
        expect(within(screen.getByRole('region', { name: 'Browsers' })).getAllByRole('button')).toHaveLength(1);
        fireEvent.click(within(terminals).getByRole('button', { name: /Analyst Terminal/ }));
        expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ agentId: 'c', resourceId: 'terminal' }));
    });
    it('acknowledges new items, preserves their row marker while open, and remembers across remounts', () => {
        const { unmount } = render(<ConversationDetails conversationId="conv" model={model()} onSelect={vi.fn()} />);
        fireEvent.click(screen.getByRole('button', { name: 'Details 1 new' }));
        expect(screen.getByRole('button', { name: 'Details' })).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByRole('button', { name: /Terminal/ })).toHaveTextContent('New');
        fireEvent.keyDown(screen.getByRole('button', { name: /Terminal/ }), { key: 'Escape' });
        expect(screen.getByRole('button', { name: 'Details' })).toHaveFocus();
        unmount();
        render(<ConversationDetails conversationId="conv" model={model()} onSelect={vi.fn()} />);
        fireEvent.click(screen.getByRole('button', { name: 'Details' }));
        expect(screen.getByRole('button', { name: /Terminal/ })).not.toHaveTextContent('New');
    });

    it('routes repeated resource selections through the same action', () => {
        const onSelect = vi.fn();
        render(<ConversationDetails conversationId="conv" model={model()} onSelect={onSelect} />);
        fireEvent.click(screen.getByRole('button', { name: /Details/ }));
        fireEvent.click(screen.getByRole('button', { name: /Terminal/ }));
        expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ agentId: 'r', resourceId: 'terminal' }));
        fireEvent.click(screen.getByRole('button', { name: /Details/ }));
        fireEvent.click(screen.getByRole('button', { name: /Terminal/ }));
        expect(onSelect).toHaveBeenCalledTimes(2);
    });

    it('acknowledges arrivals while open and closes on outside interaction', () => {
        const { rerender } = render(<ConversationDetails conversationId="conv" model={model()} onSelect={vi.fn()} />);
        fireEvent.click(screen.getByRole('button', { name: /Details/ }));
        const updated = buildConversationDetails({ ...input, turns: [{ children: [{ kind: 'file_output', path: '/new.docx' }] }] });
        rerender(<ConversationDetails conversationId="conv" model={updated} onSelect={vi.fn()} />);
        expect(screen.getByRole('button', { name: /Artifacts/ })).toHaveTextContent('New');
        fireEvent.mouseDown(document.body);
        expect(screen.getByRole('button', { name: 'Details' })).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByRole('region', { name: 'Conversation details' })).not.toBeInTheDocument();
    });

    it('uses an anchored portal and keeps focus transitions inside the disclosure open', () => {
        const { container } = render(<ConversationDetails conversationId="conv" model={model()} onSelect={vi.fn()} />);
        const trigger = screen.getByRole('button', { name: /Details/ });
        fireEvent.click(trigger);
        const region = screen.getByRole('region', { name: 'Conversation details' });
        expect(container).not.toContainElement(region);
        expect(region).toHaveAttribute('id', trigger.getAttribute('aria-controls'));
        const terminal = screen.getByRole('button', { name: /Terminal/ });
        fireEvent.blur(trigger, { relatedTarget: terminal });
        fireEvent.mouseDown(terminal);
        expect(trigger).toHaveAttribute('aria-expanded', 'true');
        fireEvent.blur(terminal, { relatedTarget: document.body });
        expect(trigger).toHaveAttribute('aria-expanded', 'false');
    });

    it('keeps Advanced collapsed and context capacity confined to the primary agent', () => {
        const data = { ...model(), contextUsage: { context_limit: 1000, context_used: 650, compaction_threshold: 0.75 } };
        render(<ConversationDetails conversationId="conv" model={data} onSelect={vi.fn()} />);
        fireEvent.click(screen.getByRole('button', { name: /Details/ }));
        expect(screen.getByText('Advanced').closest('details')).not.toHaveAttribute('open');
        fireEvent.click(screen.getByText('Advanced'));
        expect(screen.getByText('About 100 tokens until compaction')).toBeVisible();
        expect(screen.getAllByRole('progressbar')).toHaveLength(1);
    });
});
