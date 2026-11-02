import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
    { id: 'mailer', name: 'Mailer', description: 'Email helper', prompt: 'Send mail.', tool_categories: ['integration:mail'] },
];

const _categories = [
    { id: 'coding', label: 'Coding & Files', description: 'Edit code', tools: ['read_file', 'write_file'], tool_count: 2, connected: null },
    { id: 'integration:mail', label: 'Email', connection_id: 'mail', description: 'Read and send mail', tools: ['search_email'], tool_count: 1, connected: false },
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

        fireEvent.click(screen.getByRole('button', { name: 'Add' }));
        expect(screen.queryByRole('button', { name: /Reviewer/ })).not.toBeInTheDocument();

        const file = new File(['{}'], 'reviewer.skill.omnideck.json');
        fireEvent.change(screen.getByTestId('skills-import-input'), {
            target: { files: [file] },
        });

        expect(await within(screen.getByRole('dialog')).findByRole('button', { name: /Reviewer/ })).toHaveTextContent('Reviewer');
    });

    it('shows the skill library without a separate tool catalog tab', async () => {
        renderTab();
        await screen.findByTestId('skill-item-coder');
        expect(screen.getByRole('tab', { name: /My Skills/ })).toHaveTextContent('2');
        expect(screen.queryByRole('tab', { name: /Tool Categories/ })).not.toBeInTheDocument();
        expect(screen.getByPlaceholderText('Search skills…')).toBeInTheDocument();
    });

    it('filters the skill list by the search box', async () => {
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());

        fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'mail' } });
        expect(screen.getByTestId('skill-item-mailer')).toBeInTheDocument();
        expect(screen.queryByTestId('skill-item-coder')).not.toBeInTheDocument();
    });

    it('searches groups in the inline Add picker', async () => {
        const user = userEvent.setup();
        renderTab();
        await user.click(await screen.findByTestId('skill-item-mailer'));
        await user.click(screen.getByRole('button', { name: 'Add' }));
        const dialog = screen.getByRole('dialog');
        await user.type(within(dialog).getByRole('searchbox'), 'coding');
        expect(within(dialog).getByRole('button', { name: /Coding & Files/ })).toBeInTheDocument();
        expect(within(dialog).queryByRole('button', { name: /Email/ })).not.toBeInTheDocument();
    });

    it('opens the editor when a skill is selected', async () => {
        const user = userEvent.setup();
        renderTab();
        await waitFor(() => expect(screen.getByTestId('skill-item-coder')).toBeInTheDocument());
        await user.click(screen.getByTestId('skill-item-coder'));
        await waitFor(() => expect(screen.getByDisplayValue('Coder')).toBeInTheDocument());
        expect(screen.getByDisplayValue('Write code.')).toBeInTheDocument();
    });

    it('adds and removes tool groups in the skill draft and persists them on save', async () => {
        const user = userEvent.setup();
        renderTab();
        await user.click(await screen.findByTestId('skill-item-coder'));
        expect(screen.getByTestId('selected-tool:coding')).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Add' }));
        await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: /Email/ }));
        expect(screen.getByTestId('selected-tool:integration:mail')).toHaveTextContent('Email');
        expect(screen.queryByText(/Integration unavailable/)).not.toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Remove Coding & Files' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        const request = global.fetch.mock.calls.find(([url, init]) => url === '/api/skills/coder' && init?.method === 'PUT');
        expect(JSON.parse(request[1].body).tool_categories).toEqual(['integration:mail']);
    });

    it('expands a selected row to show tools without a catalog tab', async () => {
        const user = userEvent.setup();
        renderTab();
        await user.click(await screen.findByTestId('skill-item-coder'));
        const row = screen.getByTestId('selected-tool:coding');
        const toggle = within(row).getByRole('button', { name: 'Coding & Files', exact: true });
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        expect(within(row).getByText('read file')).not.toBeVisible();
        await user.click(toggle);
        expect(toggle).toHaveAttribute('aria-expanded', 'true');
        expect(within(row).getByText('read file')).toBeVisible();
        expect(within(row).getByText('write file')).toBeVisible();
    });
});
