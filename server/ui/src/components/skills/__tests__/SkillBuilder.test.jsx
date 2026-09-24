import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SkillBuilder from '../SkillBuilder.jsx';

const CATEGORIES = [
    { id: 'coding', label: 'Coding & Files', tool_count: 8, connected: null },
    { id: 'email', label: 'Email', tool_count: 7, connected: false },
];

function _skill(overrides = {}) {
    return { id: 's1', name: 'Coder', description: '', prompt: 'Write code.', tool_categories: ['coding'], ...overrides };
}

function renderBuilder(props = {}) {
    const merged = {
        skill: _skill(), categories: CATEGORIES,
        onSave: vi.fn().mockResolvedValue({ ok: true }), onDelete: vi.fn(), onExport: vi.fn(),
        ...props,
    };
    render(<SkillBuilder {...merged} />);
    return merged;
}

describe('SkillBuilder export', () => {
    it('shows an Export button for a saved skill and calls onExport', async () => {
        const user = userEvent.setup();
        const { onExport } = renderBuilder();
        await user.click(screen.getByTestId('skill-export'));
        expect(onExport).toHaveBeenCalledWith('s1');
    });

    it('hides the Export button on an unsaved draft skill', () => {
        renderBuilder({ skill: _skill({ _unsaved: true }) });
        expect(screen.queryByTestId('skill-export')).not.toBeInTheDocument();
    });
});
