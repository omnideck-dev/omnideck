import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProfileBuilder from '../ProfileBuilder.jsx';

const SKILLS = [
    { id: 'coder', name: 'Coder', tool_categories: ['coding'] },
    { id: 'browser', name: 'Web Browser', tool_categories: ['browser', 'webfetch'] },
    { id: 'assistant', name: 'Assistant', tool_categories: ['memory', 'email'] },
];

const CATEGORIES = [
    { id: 'coding', label: 'Coding & Files', tool_count: 8, connected: null },
    { id: 'browser', label: 'Web Browsing', tool_count: 16, connected: null },
    { id: 'webfetch', label: 'Web Fetch', tool_count: 1, connected: null },
    { id: 'memory', label: 'Memory', tool_count: 3, connected: null },
    { id: 'email', label: 'Email', tool_count: 7, connected: false },
];

function _profile(overrides = {}) {
    return {
        id: 'p1', name: 'Omnideck', description: '', model: 'test-model:7b', provider: 'ollama',
        system_prompt: '', skills: ['coder'], allow_spawn: true, allow_load_skills: true,
        ...overrides,
    };
}

function renderBuilder(props = {}) {
    const onSave = vi.fn().mockResolvedValue({ ok: true });
    const merged = {
        profile: _profile(), skills: SKILLS, categories: CATEGORIES, providers: [],
        onSave, onDelete: vi.fn(), onDuplicate: vi.fn(), ...props,
    };
    render(<ProfileBuilder {...merged} />);
    return { onSave, ...merged };
}

describe('ProfileBuilder skill picker + autonomy', () => {
    let _originalFetch;

    beforeEach(() => {
        _originalFetch = global.fetch;
        global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) }));
    });

    afterEach(() => {
        global.fetch = _originalFetch;
    });

    it('lists skills from the library, not a hardcoded set', async () => {
        const user = userEvent.setup();
        renderBuilder();
        await user.click(screen.getByTestId('profile-add-skill'));

        expect(screen.getByTestId('profile-skill-option-coder')).toBeInTheDocument();
        expect(screen.getByTestId('profile-skill-option-browser')).toBeInTheDocument();
        expect(screen.getByTestId('profile-skill-option-assistant')).toBeInTheDocument();
        // Regression: the old hardcoded ids are gone.
        expect(screen.queryByText(/image_gen/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/music_gen/i)).not.toBeInTheDocument();
    });

    it('filters picker options by skill name', async () => {
        const user = userEvent.setup();
        renderBuilder();
        await user.click(screen.getByTestId('profile-add-skill'));

        const search = screen.getByPlaceholderText('Search your skills…');
        await user.type(search, 'web');

        expect(screen.getByTestId('profile-skill-option-browser')).toBeInTheDocument();
        expect(screen.queryByTestId('profile-skill-option-coder')).not.toBeInTheDocument();
        expect(screen.queryByTestId('profile-skill-option-assistant')).not.toBeInTheDocument();

        await user.clear(search);
        await user.type(search, 'missing');
        expect(screen.getByText('No skills match.')).toBeInTheDocument();
    });

    it('renders the profile\'s skills as chips and removes one on save', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();
        const chip = screen.getByTestId('profile-skill-coder');
        expect(chip).toHaveTextContent('Coder');

        await user.click(within(chip).getByRole('button', { name: 'Remove Coder' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: [] }));
    });

    it('adds a skill from the picker and serializes it on save', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();
        await user.click(screen.getByTestId('profile-add-skill'));
        await user.click(screen.getByTestId('profile-skill-option-browser'));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(
            expect.objectContaining({ skills: expect.arrayContaining(['coder', 'browser']) }),
        );
    });

    it('closes the picker on Escape and on outside click', async () => {
        const user = userEvent.setup();
        renderBuilder();

        await user.click(screen.getByTestId('profile-add-skill'));
        expect(screen.getByTestId('profile-skill-picker')).toBeInTheDocument();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByTestId('profile-skill-picker')).not.toBeInTheDocument();

        await user.click(screen.getByTestId('profile-add-skill'));
        expect(screen.getByTestId('profile-skill-picker')).toBeInTheDocument();
        fireEvent.mouseDown(document.body);
        expect(screen.queryByTestId('profile-skill-picker')).not.toBeInTheDocument();
    });

    it('renders autonomy toggles on by default and serializes a change', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();

        const spawn = screen.getByRole('switch', { name: 'Allow spawning agents' });
        const load = screen.getByRole('switch', { name: 'Allow loading skills mid-conversation' });
        expect(spawn).toBeChecked();
        expect(load).toBeChecked();

        await user.click(spawn);
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ allow_spawn: false }));
    });

    it('legacy profile without autonomy fields shows toggles on', () => {
        renderBuilder({ profile: _profile({ allow_spawn: undefined, allow_load_skills: undefined }) });
        expect(screen.getByRole('switch', { name: 'Allow spawning agents' })).toBeChecked();
        expect(screen.getByRole('switch', { name: 'Allow loading skills mid-conversation' })).toBeChecked();
    });

    it('disables Save on a new profile until a model is chosen', () => {
        renderBuilder({ profile: _profile({ model: '', _unsaved: true }) });
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
        expect(screen.getByTestId('profile-model-required')).toBeInTheDocument();
    });

    it('enables Save on a new profile once a model is set', () => {
        renderBuilder({ profile: _profile({ model: 'test-model:7b', _unsaved: true }) });
        expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
        expect(screen.queryByTestId('profile-model-required')).not.toBeInTheDocument();
    });

    it('lets an existing model-less profile be saved (e.g. to disable or rename it)', () => {
        renderBuilder({ profile: _profile({ model: '' }) });
        expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
        expect(screen.queryByTestId('profile-model-required')).not.toBeInTheDocument();
    });

    it('does not call onSave when a new profile has no model', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder({ profile: _profile({ model: '', _unsaved: true }) });
        // The button is disabled, but guard the handler too.
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).not.toHaveBeenCalled();
    });

    it('shows an Export button for a saved profile and calls onExport', async () => {
        const user = userEvent.setup();
        const onExport = vi.fn();
        renderBuilder({ onExport });
        await user.click(screen.getByTestId('profile-export'));
        expect(onExport).toHaveBeenCalledWith('p1');
    });

    it('hides the Export button on an unsaved draft profile', () => {
        renderBuilder({ profile: _profile({ _unsaved: true }), onExport: vi.fn() });
        expect(screen.queryByTestId('profile-export')).not.toBeInTheDocument();
    });

    it('surfaces a save error as a Callout alert', async () => {
        const user = userEvent.setup();
        const onSave = vi.fn().mockResolvedValue({
            ok: false,
            error: { error: 'default_agent_cannot_be_disabled', message: 'Change the default agent first.' },
        });
        renderBuilder({ onSave });

        await user.click(screen.getByRole('button', { name: 'Save' }));
        const alert = await screen.findByTestId('profile-save-error');
        expect(within(alert).getByRole('alert')).toBeInTheDocument();
        expect(alert).toHaveTextContent("Can't disable the default agent");
        expect(alert).toHaveTextContent('Change the default agent first.');
    });
});
