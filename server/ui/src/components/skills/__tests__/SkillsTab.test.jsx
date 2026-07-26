import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppDataProvider, useAppData } from '../../../contexts/AppData.jsx';
import { importPackFile } from '../../../utils/packs.js';
import ProfileBuilder from '../../ProfileBuilder.jsx';
import { ToastProvider } from '../../ToastProvider.jsx';
import SkillsTab from '../SkillsTab.jsx';

vi.mock('../../../hooks/useAgentProfiles.js', () => ({
    default: () => ({ profiles: [] }),
}));

vi.mock('../../../hooks/useFeatures.js', () => ({
    default: () => ({ features: {}, loaded: true, refresh: vi.fn() }),
}));

vi.mock('../../../utils/packs.js', async (importOriginal) => ({
    ...(await importOriginal()),
    importPackFile: vi.fn(),
}));

// SkillsTab reads useToast for import feedback, so every render needs a provider.
const renderTab = (extra = null) => render(
    <AppDataProvider>
        <ToastProvider>
            <SkillsTab />
            {extra}
        </ToastProvider>
    </AppDataProvider>,
);

const _skills = [
    { id: 'coder', name: 'Coder', description: 'Write code', prompt: 'Write code.', tool_categories: ['coding'] },
    { id: 'mailer', name: 'Mailer', description: 'Email helper', prompt: 'Send mail.', tool_categories: ['email'] },
];

const _categories = [
    { id: 'coding', label: 'Coding & Files', description: 'Edit code', tools: ['read_file', 'write_file'], tool_count: 2, connected: null },
    { id: 'email', label: 'Email', description: 'Read and send mail', tools: ['search_email'], tool_count: 1, connected: false },
];

function _ok(body) {
    return Promise.resolve({ ok: true, status: 200, json: async () => body });
}

function AgentProfileSkillPicker() {
    const { skillsHook } = useAppData();
    return (
        <ProfileBuilder
            profile={{
                id: 'agent',
                name: 'Agent',
                provider: '',
                model: '',
                system_prompt: '',
                skills: [],
            }}
            providers={[]}
            skills={skillsHook.skills}
            categories={[]}
        />
    );
}

describe('SkillsTab', () => {
    let _originalFetch;

    beforeEach(() => {
        importPackFile.mockReset();
        _originalFetch = global.fetch;
        global.fetch = vi.fn((url, init) => {
            if (url === '/api/skills' && (!init || init.method === undefined)) return _ok(_skills);
            if (url === '/api/tool-categories') return _ok(_categories);
            return _ok({});
        });
    });

    afterEach(() => {
        global.fetch = _originalFetch;
    });

    it('renders a row per skill from /api/skills', async () => {
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        expect(screen.getByText('Coder')).toBeInTheDocument();
        expect(screen.getByText('Mailer')).toBeInTheDocument();
    });

    it('makes an imported skill immediately available in the agent profile picker', async () => {
        const importedSkill = {
            id: 'reviewer',
            name: 'Reviewer',
            description: 'Review changes',
            prompt: 'Review changes.',
            tool_categories: [],
        };
        importPackFile.mockResolvedValue({
            ok: true,
            data: { profiles: [], skills: [importedSkill] },
        });
        renderTab(<AgentProfileSkillPicker />);
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());

        fireEvent.click(screen.getByTestId('profile-add-skill'));
        expect(screen.queryByTestId('profile-skill-option-reviewer')).not.toBeInTheDocument();

        const file = new File(['{}'], 'reviewer.skill.omnideck.json');
        fireEvent.change(screen.getByTestId('skills-import-input'), {
            target: { files: [file] },
        });

        expect(await screen.findByTestId('profile-skill-option-reviewer')).toHaveTextContent('Reviewer');
    });

    it('shows the skill and category counts in the view tabs', async () => {
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        expect(screen.getByRole('tab', { name: /My Skills/ })).toHaveTextContent('2');
        await waitFor(() => expect(screen.getByRole('tab', { name: /Tool Categories/ })).toHaveTextContent('2'));
    });

    it('uses a per-view search placeholder', async () => {
        const user = userEvent.setup();
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        expect(screen.getByPlaceholderText('Search skills…')).toBeInTheDocument();

        await user.click(screen.getByRole('tab', { name: /Tool Categories/ }));
        expect(screen.getByPlaceholderText('Search tool categories…')).toBeInTheDocument();
    });

    it('filters the skill list by the search box', async () => {
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());

        fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'mail' } });
        expect(screen.getByTestId('skill-item-mailer')).toBeInTheDocument();
        expect(screen.queryByTestId('skill-item-coder')).not.toBeInTheDocument();
    });

    it('filters the tool categories by the search box', async () => {
        const user = userEvent.setup();
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        await user.click(screen.getByRole('tab', { name: /Tool Categories/ }));
        await waitFor(() => expect(screen.getByTestId('cat-row-coding')).toBeInTheDocument());

        fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'email' } });
        expect(screen.getByTestId('cat-row-email')).toBeInTheDocument();
        expect(screen.queryByTestId('cat-row-coding')).not.toBeInTheDocument();
    });

    it('opens the editor when a skill is selected', async () => {
        const user = userEvent.setup();
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        await user.click(screen.getByTestId('skill-item-coder'));
        await waitFor(() => expect(screen.getByDisplayValue('Coder')).toBeInTheDocument());
        expect(screen.getByDisplayValue('Write code.')).toBeInTheDocument();
    });

    it('reflects and toggles a category chip active state', async () => {
        const user = userEvent.setup();
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        await user.click(screen.getByTestId('skill-item-coder'));
        await waitFor(() => expect(screen.getByTestId('cat-chip-coding')).toBeInTheDocument());

        // Coder grants 'coding' but not 'email'.
        expect(screen.getByTestId('cat-chip-coding')).toHaveAttribute('aria-pressed', 'true');
        const emailChip = screen.getByTestId('cat-chip-email');
        expect(emailChip).toHaveAttribute('aria-pressed', 'false');

        await user.click(emailChip);
        expect(emailChip).toHaveAttribute('aria-pressed', 'true');
    });

    it('shows a connection dot only on integration category chips', async () => {
        const user = userEvent.setup();
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        await user.click(screen.getByTestId('skill-item-coder'));
        await waitFor(() => expect(screen.getByTestId('cat-chip-email')).toBeInTheDocument());

        expect(screen.getByTestId('cat-dot-email')).toBeInTheDocument();
        expect(screen.queryByTestId('cat-dot-coding')).not.toBeInTheDocument();
    });

    it('lists tool categories and expands a card to show its tools', async () => {
        const user = userEvent.setup();
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());

        await user.click(screen.getByRole('tab', { name: /Tool Categories/ }));
        await waitFor(() => expect(screen.getByTestId('cat-row-coding')).toBeInTheDocument());

        // Tools are hidden until the row is expanded.
        expect(screen.queryByTestId('cat-tools-coding')).not.toBeInTheDocument();
        await user.click(screen.getByTestId('cat-row-coding'));
        await waitFor(() => expect(screen.getByTestId('cat-tools-coding')).toBeInTheDocument());
        expect(screen.getByText('read_file')).toBeInTheDocument();
        expect(screen.getByText('write_file')).toBeInTheDocument();
    });
});
