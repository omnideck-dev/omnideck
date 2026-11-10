import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import SelectionToolList from '../SelectionToolList.jsx';

const category = { label: 'Work tools', operations: [
    { id: 'mcp.search', title: 'Search messages', description: '# Long model instructions\nNever render these here.' },
    { id: 'email.messages.send', title: 'Send email', description: 'Send an email message through the connected account.' },
] };

function clip(button, childIndex = 0) {
    Object.defineProperty(button.children[childIndex], 'scrollWidth', { configurable: true, value: 500 });
    Object.defineProperty(button.children[childIndex], 'clientWidth', { configurable: true, value: 100 });
}

describe('SelectionToolList', () => {
    it('falls back to the MCP tool name when no title is provided', () => {
        render(<SelectionToolList category={{ label: 'MCP', operations: [
            { id: 'mcp.read_value', description: 'Instructions for the model' },
        ] }} />);
        expect(screen.getByRole('button', { name: 'read_value', exact: true })).toBeVisible();
        expect(screen.queryByText('Instructions for the model')).not.toBeInTheDocument();
    });

    it('shows only MCP titles, but keeps native short descriptions and the original catalog intact', () => {
        render(<SelectionToolList category={category} />);
        expect(screen.getByRole('button', { name: 'Search messages', exact: true })).toBeVisible();
        expect(screen.queryByText(/Long model instructions/)).not.toBeInTheDocument();
        expect(screen.getByText(category.operations[1].description)).toBeVisible();
        expect(category.operations[0].description).toContain('Long model instructions');
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('reveals a clipped MCP title on hover without revealing its model description', async () => {
        const user = userEvent.setup();
        render(<SelectionToolList category={category} />);
        const button = screen.getByRole('button', { name: 'Search messages', exact: true });
        clip(button);
        await user.hover(button);
        expect(screen.getByRole('tooltip')).toHaveTextContent('Search messages');
        expect(screen.getByRole('tooltip')).not.toHaveTextContent('Long model instructions');
        await user.keyboard('{Escape}');
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('reveals clipped native descriptions on keyboard focus and dismisses on blur', async () => {
        const user = userEvent.setup();
        render(<SelectionToolList category={category} />);
        const button = screen.getByRole('button', { name: /Send email/ });
        clip(button, 1);
        await user.tab();
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
        await user.tab();
        expect(button).toHaveFocus();
        expect(screen.getByRole('tooltip')).toHaveTextContent(category.operations[1].description);
        expect(button).toHaveAccessibleDescription(/Send an email message/);
        await user.tab();
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('supports tap/click for clipped text and never opens details for text that fits', async () => {
        const user = userEvent.setup();
        render(<SelectionToolList category={category} />);
        const button = screen.getByRole('button', { name: 'Search messages', exact: true });
        await user.click(button);
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
        clip(button);
        fireEvent.click(button);
        expect(screen.getByRole('tooltip')).toBeVisible();
        fireEvent.mouseDown(document.body);
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('renders built-in tool names without an individual expand control', () => {
        render(<SelectionToolList category={{ label: 'Memory', tools: ['remember', 'load_memory'] }} />);
        const list = screen.getByRole('list', { name: 'Memory tools' });
        expect(within(list).getByRole('button', { name: 'load memory' })).not.toHaveAttribute('aria-expanded');
    });
});
