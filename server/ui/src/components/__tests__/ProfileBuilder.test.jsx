import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProfileBuilder from '../ProfileBuilder.jsx';
import { BrowserProfilesCatalogProvider } from '../../features/browser/BrowserProfilesContext.jsx';
import useBrowserProfiles from '../../features/browser/useBrowserProfiles.js';

const SKILLS = [
    { id: 'coder', name: 'Coder', tool_categories: ['coding'] },
    { id: 'assistant', name: 'Assistant', tool_categories: ['memory', 'email'] },
];

const CATEGORIES = [
    { id: 'coding', label: 'Coding & Files', tool_count: 8, connected: null },
    { id: 'memory', label: 'Memory', tool_count: 3, connected: null },
    { id: 'email', label: 'Email', tool_count: 7, connected: false },
];

function _profile(overrides = {}) {
    return {
        id: 'p1', name: 'Omnideck', description: '', model: 'test-model:7b', provider: 'ollama',
        system_prompt: '', skills: ['coder'], allow_spawn: true, allow_load_skills: true,
        browser_profile_id: null,
        ...overrides,
    };
}

function renderBuilder(props = {}) {
    const onSave = vi.fn().mockResolvedValue({ ok: true });
    const merged = {
        profile: _profile(), skills: SKILLS, categories: CATEGORIES, providers: [],
        onSave, onDelete: vi.fn(), onDuplicate: vi.fn(), onBack: vi.fn(), ...props,
    };
    function Wrapper({ children }) {
        const catalog = useBrowserProfiles();
        return (
            <BrowserProfilesCatalogProvider value={catalog}>
                {children}
            </BrowserProfilesCatalogProvider>
        );
    }
    render(<ProfileBuilder {...merged} />, { wrapper: Wrapper });
    return { onSave, ...merged };
}

describe('ProfileBuilder skill picker + autonomy', () => {
    let _originalFetch;

    beforeEach(() => {
        _originalFetch = global.fetch;
        global.fetch = vi.fn(() => Promise.resolve({
            ok: true,
            json: async () => [{ id: 'default', name: 'Default', icon: 'bi-globe2' }],
        }));
    });

    afterEach(() => {
        vi.useRealTimers();
        global.fetch = _originalFetch;
    });

    it('shows a save confirmation only after saving and clears it after three seconds', async () => {
        vi.useFakeTimers();
        renderBuilder();
        expect(screen.getByRole('status')).toBeEmptyDOMElement();
        fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Updated' } });
        expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes');
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
        expect(screen.getByRole('status')).toHaveTextContent('Changes saved');
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
        act(() => vi.advanceTimersByTime(2999));
        expect(screen.getByRole('status')).toHaveTextContent('Changes saved');
        act(() => vi.advanceTimersByTime(1));
        expect(screen.getByRole('status')).toBeEmptyDOMElement();
    });

    it('keeps new edits visible and gives each subsequent save its own confirmation timer', async () => {
        vi.useFakeTimers();
        renderBuilder();
        const name = screen.getByRole('textbox', { name: 'Name' });
        fireEvent.change(name, { target: { value: 'First edit' } });
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
        act(() => vi.advanceTimersByTime(2000));
        fireEvent.change(name, { target: { value: 'Second edit' } });
        act(() => vi.advanceTimersByTime(5000));
        expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes');
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
        act(() => vi.advanceTimersByTime(2999));
        expect(screen.getByRole('status')).toHaveTextContent('Changes saved');
        act(() => vi.advanceTimersByTime(1));
        expect(screen.getByRole('status')).toBeEmptyDOMElement();
        fireEvent.change(name, { target: { value: 'Discard this' } });
        fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
        expect(screen.getByRole('status')).toBeEmptyDOMElement();
    });

    it('does not auto-dismiss save errors or unsaved changes', async () => {
        vi.useFakeTimers();
        renderBuilder({ onSave: vi.fn().mockResolvedValue({ ok: false, error: { message: 'Try again.' } }) });
        fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Unsaved' } });
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
        act(() => vi.advanceTimersByTime(10000));
        expect(screen.getByTestId('profile-save-error')).toHaveTextContent('Try again.');
        expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes');
        expect(screen.queryByText('Changes saved')).not.toBeInTheDocument();
    });

    it('edits instructions without displaying word or token counts', async () => {
        renderBuilder({ profile: _profile({ system_prompt: 'Keep it brief.' }) });
        const instructions = screen.getByRole('textbox', { name: 'Instructions' });
        const section = within(instructions.closest('section'));
        expect(instructions).toHaveValue('Keep it brief.');
        expect(section.queryByText(/\b\d+\s+(words?|tokens?)\b/i)).not.toBeInTheDocument();
        fireEvent.change(instructions, { target: { value: 'Help' } });
        expect(instructions).toHaveValue('Help');
        expect(section.queryByText(/\b\d+\s+(words?|tokens?)\b/i)).not.toBeInTheDocument();
    });

    it('lists skills from the library, not a hardcoded set', async () => {
        const user = userEvent.setup();
        renderBuilder();
        await user.click(screen.getByRole('button', { name: 'Add' }));

        expect(within(screen.getByRole('dialog')).queryByRole('button', { name: 'Coder' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Assistant' })).toBeInTheDocument();
        expect(screen.queryByText('Web Browser')).not.toBeInTheDocument();
        // Regression: the old hardcoded ids are gone.
        expect(screen.queryByText(/image_gen/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/music_gen/i)).not.toBeInTheDocument();
    });

    it('filters picker options by skill name', async () => {
        const user = userEvent.setup();
        renderBuilder();
        await user.click(screen.getByRole('button', { name: 'Add' }));

        const search = screen.getByPlaceholderText('Search…');
        await user.type(search, 'assist');

        expect(screen.getByRole('button', { name: 'Assistant' })).toBeInTheDocument();
        expect(within(screen.getByRole('dialog')).queryByRole('button', { name: 'Coder' })).not.toBeInTheDocument();

        await user.clear(search);
        await user.type(search, 'missing');
        expect(screen.getByText('Nothing matches your search.')).toBeInTheDocument();
    });

    it('renders the profile\'s skills as removable rows and removes one on save', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();
        const chip = screen.getByTestId('selected-skill:coder');
        expect(chip).toHaveTextContent('Coder');

        await user.click(within(chip).getByRole('button', { name: 'Remove Coder' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: [] }));
    });

    it('adds a skill from the picker and serializes it on save', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();
        await user.click(screen.getByRole('button', { name: 'Add' }));
        await user.click(screen.getByRole('button', { name: 'Assistant' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(
            expect.objectContaining({ skills: expect.arrayContaining(['coder', 'assistant']) }),
        );
    });

    it('saves built-in groups directly without adding a skill', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();
        await user.click(screen.getByRole('button', { name: 'Add' }));
        await user.click(screen.getByRole('button', { name: 'Memory' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: ['coder'], tool_categories: ['memory'] }));
    });

    it('configures Browser access separately and defaults to Default', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();
        expect(screen.queryByTestId('agent-browser-profile-select')).not.toBeInTheDocument();

        await user.click(screen.getByRole('switch', { name: 'Let this agent open websites' }));
        const select = await screen.findByTestId('agent-browser-profile-select');
        expect(screen.getByText('Start from')).toBeInTheDocument();
        expect(select).toHaveAttribute('data-value', 'default');

        await user.click(select);
        await user.click(screen.getByRole('option', { name: 'Empty' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
            browser_profile_id: 'empty',
        }));
    });

    it('clears the hidden profile assignment when Browser access is disabled', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder({
            profile: _profile({ browser_profile_id: 'default' }),
        });
        await screen.findByTestId('agent-browser-profile-select');

        await user.click(screen.getByRole('switch', { name: 'Let this agent open websites' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));

        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
            browser_profile_id: null,
        }));
    });

    it('closes the picker on Escape and on outside click', async () => {
        const user = userEvent.setup();
        renderBuilder();

        await user.click(screen.getByRole('button', { name: 'Add' }));
        expect(screen.getByRole('dialog', { name: 'Add skills and tools' })).toBeInTheDocument();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('dialog', { name: 'Add skills and tools' })).not.toBeInTheDocument();

        await user.click(screen.getByRole('button', { name: 'Add' }));
        expect(screen.getByRole('dialog', { name: 'Add skills and tools' })).toBeInTheDocument();
        fireEvent.mouseDown(document.body);
        expect(screen.queryByRole('dialog', { name: 'Add skills and tools' })).not.toBeInTheDocument();
    });

    it('renders autonomy toggles on by default and serializes a change', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder();

        const spawn = screen.getByRole('switch', { name: 'Delegate tasks to other agents' });
        const load = screen.getByRole('switch', { name: 'Load more skills during a conversation' });
        expect(spawn).toBeChecked();
        expect(load).toBeChecked();

        await user.click(spawn);
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ allow_spawn: false }));
    });

    it('legacy profile without autonomy fields shows toggles on', () => {
        renderBuilder({ profile: _profile({ allow_spawn: undefined, allow_load_skills: undefined }) });
        expect(screen.getByRole('switch', { name: 'Delegate tasks to other agents' })).toBeChecked();
        expect(screen.getByRole('switch', { name: 'Load more skills during a conversation' })).toBeChecked();
    });

    it('offers Create agent without saved-item actions and explains the required model', () => {
        renderBuilder({ profile: _profile({ model: '', _unsaved: true }) });
        expect(screen.getByRole('button', { name: 'Create agent' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Create agent' })).toHaveAccessibleDescription('Choose a model to create this agent.');
        expect(screen.queryByRole('button', { name: 'More actions' })).not.toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('Not created yet');
        expect(screen.getByTestId('profile-model-required')).toBeInTheDocument();
    });

    it('enables Create agent on a new profile once a model is set', () => {
        renderBuilder({ profile: _profile({ model: 'test-model:7b', _unsaved: true }) });
        expect(screen.getByRole('button', { name: 'Create agent' })).toBeEnabled();
        expect(screen.queryByTestId('profile-model-required')).not.toBeInTheDocument();
    });

    it('lets an existing model-less profile be saved after an edit', async () => {
        const user = userEvent.setup();
        renderBuilder({ profile: _profile({ model: '' }) });
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
        await user.type(screen.getByRole('textbox', { name: 'Name' }), ' renamed');
        expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
        expect(screen.queryByTestId('profile-model-required')).not.toBeInTheDocument();
    });

    it('does not call onSave when a new profile has no model', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder({ profile: _profile({ model: '', _unsaved: true }) });
        // The button is disabled, but guard the handler too.
        await user.click(screen.getByRole('button', { name: 'Create agent' }));
        expect(onSave).not.toHaveBeenCalled();
    });

    it('shows an Export button for a saved profile and calls onExport', async () => {
        const user = userEvent.setup();
        const onExport = vi.fn();
        renderBuilder({ onExport });
        await user.click(screen.getByRole('button', { name: 'More actions' }));
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
        await user.click(screen.getByRole('switch', { name: 'Available in chat and to other agents' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        const alert = await screen.findByTestId('profile-save-error');
        expect(within(alert).getByRole('alert')).toBeInTheDocument();
        expect(alert).toHaveTextContent("Can't disable the default agent");
        expect(alert).toHaveTextContent('Change the default agent first.');
    });

    it('discards all unsaved settings and resets the dirty signal', async () => {
        const user = userEvent.setup();
        const onDirtyChange = vi.fn();
        renderBuilder({ onDirtyChange });
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
        await user.type(screen.getByRole('textbox', { name: 'Name' }), ' revised');
        await user.type(screen.getByRole('textbox', { name: 'Instructions' }), 'Plan my day');
        await user.click(screen.getByRole('switch', { name: 'Delegate tasks to other agents' }));
        await user.click(screen.getByRole('button', { name: 'Remove Coder' }));
        expect(onDirtyChange).toHaveBeenLastCalledWith(true);
        await user.click(screen.getByRole('button', { name: 'Discard' }));
        expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Omnideck');
        expect(screen.getByRole('textbox', { name: 'Instructions' })).toHaveValue('');
        expect(screen.getByTestId('selected-skill:coder')).toBeInTheDocument();
        expect(screen.getByRole('switch', { name: 'Delegate tasks to other agents' })).toBeChecked();
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
        expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    });

    it('keeps model tuning collapsed and tool limits in Autonomy', async () => {
        const user = userEvent.setup();
        const { onSave } = renderBuilder({ profile: _profile({ max_iterations: 25 }) });
        const disclosure = screen.getByText('Model settings').closest('details');
        expect(disclosure).not.toHaveAttribute('open');
        expect(screen.getAllByTestId('field-max_iterations')).toHaveLength(1);
        await user.clear(screen.getByRole('spinbutton', { name: 'Tool steps per message' }));
        await user.click(screen.getByText('Model settings'));
        expect(disclosure).toHaveAttribute('open');
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ max_iterations: null }));
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    });

    it('preserves edits on a network failure and allows retry', async () => {
        const user = userEvent.setup();
        const onSave = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ok: true });
        renderBuilder({ onSave });
        await user.type(screen.getByRole('textbox', { name: 'Instructions' }), 'Keep it brief');
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('Check your connection');
        expect(screen.getByRole('textbox', { name: 'Instructions' })).toHaveValue('Keep it brief');
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(onSave).toHaveBeenCalledTimes(2);
    });

    it('restores the chosen browser profile when access is toggled back on', async () => {
        const user = userEvent.setup();
        renderBuilder({ profile: _profile({ browser_profile_id: 'empty' }) });
        const toggle = screen.getByRole('switch', { name: 'Let this agent open websites' });
        await user.click(toggle);
        await user.click(toggle);
        expect(screen.getByTestId('agent-browser-profile-select')).toHaveAttribute('data-value', 'empty');
    });

    it('chooses an icon and requires confirmation for deletion in More', async () => {
        const user = userEvent.setup();
        const { onSave, onDelete } = renderBuilder();
        await user.click(screen.getByRole('button', { name: 'Change agent icon' }));
        await user.click(screen.getByRole('menuitemradio', { name: 'bookshelf' }));
        await user.click(screen.getByRole('button', { name: 'Save' }));
        expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ icon: 'bi-bookshelf' }));
        await user.click(screen.getByRole('button', { name: 'More actions' }));
        await user.keyboard('{Escape}');
        expect(screen.getByRole('button', { name: 'More actions' })).toHaveFocus();
        await user.click(screen.getByRole('button', { name: 'More actions' }));
        await user.click(screen.getByRole('menuitem', { name: 'Delete agent' }));
        expect(onDelete).not.toHaveBeenCalled();
        await user.click(screen.getByRole('menuitem', { name: 'Confirm delete?' }));
        expect(onDelete).toHaveBeenCalledWith('p1');
    });
});
