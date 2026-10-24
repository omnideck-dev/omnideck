import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ToolSelection from '../ToolSelection.jsx';

const integration = { id: 'integration:work', connection_id: 'work', label: 'Work Google', description: 'Work account', connected: true, tool_count: 1,
    operations: [{ id: 'email.search', title: 'Search mail', description: 'Find messages.' }] };
const skill = { id: 'triage', name: 'Inbox triage', description: 'Sort mail', tool_categories: [integration.id] };

describe('Unified selections', () => {
    it('disables Add when there are no remaining choices instead of opening an empty picker', async () => {
        const user = userEvent.setup();
        render(<ToolSelection categories={[integration]} categoryIds={[integration.id]} onCategoriesChange={vi.fn()} />);
        const add = screen.getByRole('button', { name: 'Add' });
        expect(add).toBeDisabled();
        await user.click(add);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('removes a direct row without changing skill selections or explaining inheritance', async () => {
        const user = userEvent.setup();
        const onCategoriesChange = vi.fn(), onSkillsChange = vi.fn();
        const { rerender } = render(<ToolSelection skills={[skill]} categories={[integration]} skillIds={['triage']} categoryIds={[integration.id]}
            onCategoriesChange={onCategoriesChange} onSkillsChange={onSkillsChange} />);
        await user.click(screen.getByRole('button', { name: 'Remove Work Google' }));
        expect(onCategoriesChange).toHaveBeenCalledWith([]);
        expect(onSkillsChange).not.toHaveBeenCalled();
        rerender(<ToolSelection skills={[skill]} categories={[integration]} skillIds={['triage']} categoryIds={[]}
            onCategoriesChange={onCategoriesChange} onSkillsChange={onSkillsChange} />);
        expect(screen.getByTestId('selected-skill:triage')).toBeInTheDocument();
        expect(screen.queryByText(/Also provided|stays available|Also added/)).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Add' })).toHaveFocus();
    });

    it('opens the exact integration and displays read-only approved operations', async () => {
        const user = userEvent.setup(), onOpenIntegration = vi.fn();
        render(<ToolSelection categories={[integration]} categoryIds={[integration.id]} onOpenIntegration={onOpenIntegration} />);
        await user.click(screen.getByText('Work Google'));
        expect(screen.getByText('Search mail')).toBeVisible();
        expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: /Manage in Integrations/ }));
        expect(onOpenIntegration).toHaveBeenCalledWith('work');
    });

    it('keeps missing selections visible rather than silently granting a replacement', () => {
        render(<ToolSelection categories={[integration]} categoryIds={['integration:deleted']} />);
        expect(screen.getByTestId('selected-tool:integration:deleted')).toHaveTextContent('Integration');
        expect(screen.queryByText(/No longer available|Integration unavailable/)).not.toBeInTheDocument();
        expect(screen.queryByTestId('selected-tool:integration:work')).not.toBeInTheDocument();
    });

    it('shows skill groups immediately after expanding the skill, without nested disclosures', async () => {
        const user = userEvent.setup();
        render(<ToolSelection skills={[skill]} categories={[integration]} skillIds={[skill.id]} />);
        await user.click(screen.getByRole('button', { name: skill.name, exact: true }));
        expect(screen.getByRole('region', { name: 'Work Google' })).toBeVisible();
        expect(screen.getByText('Find messages.')).toBeVisible();
        expect(document.querySelector('details')).toBeNull();
    });

    it('groups picker options, focuses search, and returns focus after keyboard selection', async () => {
        const user = userEvent.setup(), onCategoriesChange = vi.fn();
        render(<ToolSelection skills={[skill]} categories={[integration, { id: 'memory', label: 'Memory' }]}
            onSkillsChange={vi.fn()} onCategoriesChange={onCategoriesChange} />);
        await user.click(screen.getByRole('button', { name: 'Add' }));
        const dialog = screen.getByRole('dialog');
        expect(within(dialog).getByRole('searchbox')).toHaveFocus();
        for (const label of ['Skills', 'Built-in tools', 'Integrations']) expect(within(dialog).getByRole('region', { name: label })).toBeInTheDocument();
        await user.type(within(dialog).getByRole('searchbox'), 'Work Google');
        await user.tab();
        expect(screen.getByRole('button', { name: 'Clear search' })).toHaveFocus();
        await user.tab();
        expect(within(dialog).getByRole('button', { name: /Work Google/ })).toHaveFocus();
        await user.keyboard('{Enter}');
        expect(onCategoriesChange).toHaveBeenCalledWith(['integration:work']);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Add' })).toHaveFocus();
    });

    it('leaves connection status in Integrations, not on skills or direct selections', () => {
        render(<ToolSelection skills={[skill]} categories={[{ ...integration, connected: false, tool_count: 0 }]}
            skillIds={['triage']} categoryIds={[integration.id]} />);
        expect(screen.getByTestId('selected-skill:triage')).toHaveTextContent('Inbox triage');
        expect(screen.getByTestId('selected-tool:integration:work')).toHaveTextContent('Work Google');
        expect(screen.queryByText(/unavailable|No approved tools|No longer available/i)).not.toBeInTheDocument();
    });
});
