import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import AgentsView from '../AgentsView.jsx';
import { ToastProvider } from '../../ToastProvider.jsx';
import { importPackFile } from '../../../utils/packs.js';

const PROFILES = [
    {
        id: 'p1', name: 'Researcher', description: 'Web research', icon: '🔎',
        model: 'gpt-4o', provider: 'openai', skills: ['s1', 's2'], enabled: true,
    },
    {
        id: 'p2', name: 'Coder', description: 'Writes code', icon: '🤖',
        model: 'claude', provider: 'anthropic', skills: [], enabled: false,
    },
];

const profilesHook = {
    profiles: PROFILES,
    selectedProfileId: null,
    setSelectedProfileId: vi.fn(),
    createProfile: vi.fn(),
    updateProfile: vi.fn(),
    deleteProfile: vi.fn(),
    duplicateProfile: vi.fn(),
    addProfiles: vi.fn(),
};

const skillsHook = { skills: [], addSkills: vi.fn() };
const providersHook = { providers: [{ name: 'openai' }] };
vi.mock('../../../contexts/AppData.jsx', () => ({
    useAppData: () => ({ profilesHook, providersHook, skillsHook, features: {} }),
}));

// Import goes through the real utils, but the network call is stubbed so the
// test drives the handler's merge-into-lists behaviour deterministically.
vi.mock('../../../utils/packs.js', async (importOriginal) => ({
    ...(await importOriginal()),
    importPackFile: vi.fn(),
}));

// The detail is the full ProfileBuilder editor; stub it to keep this test
// focused on the list → detail routing. Render the profile name so we can
// assert which agent (or the unsaved draft) opened, plus a button that
// simulates an edit by reporting dirty state up (drives the unsaved guard).
vi.mock('../../ProfileBuilder.jsx', () => ({
    default: ({ profile, onDirtyChange }) => (
        <div data-testid="profile-builder">
            {profile?.name}
            <button type="button" data-testid="mock-edit" onClick={() => onDirtyChange?.(true)}>
                edit
            </button>
        </div>
    ),
}));

// ToastProvider is a real dependency (AgentsView surfaces delete conflicts
// through it), so render inside a provider rather than mocking it.
const renderView = () => render(<AgentsView />, { wrapper: ToastProvider });

beforeEach(() => {
    profilesHook.deleteProfile.mockReset();
    profilesHook.deleteProfile.mockResolvedValue({ conflict: false });
    profilesHook.duplicateProfile.mockReset();
    profilesHook.duplicateProfile.mockResolvedValue({ id: 'p1_copy', name: 'Researcher copy' });
    profilesHook.addProfiles.mockClear();
    skillsHook.addSkills.mockClear();
    importPackFile.mockReset();
    global.fetch = vi.fn((url) => {
        const u = String(url);
        if (u === '/api/tool-categories') {
            return Promise.resolve({ json: async () => [] });
        }
        return Promise.resolve({ json: async () => ({}) });
    });
});

afterEach(() => { vi.restoreAllMocks(); });

test('lists agents in the table', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());
    expect(screen.getByText('Coder')).toBeInTheDocument();
    expect(screen.getAllByTestId('agent-row')).toHaveLength(2);
});

test('shows a status badge for enabled and disabled agents', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('ACTIVE')).toBeInTheDocument());
    expect(screen.getByText('DISABLED')).toBeInTheDocument();
});

test('search filters the list', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('agents-search'), { target: { value: 'coder' } });
    expect(screen.getByText('Coder')).toBeInTheDocument();
    expect(screen.queryByText('Researcher')).not.toBeInTheDocument();
});

test('clicking an agent opens its detail full-width; back returns to the list', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Researcher'));
    expect(await screen.findByTestId('agent-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('agents-list')).not.toBeInTheDocument();
    expect(screen.getByTestId('profile-builder')).toHaveTextContent('Researcher');

    fireEvent.click(screen.getByTestId('agent-detail-back'));
    await waitFor(() => expect(screen.getByTestId('agents-list')).toBeInTheDocument());
});

test('New agent opens the editor with an unsaved draft', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('agents-new'));
    expect(await screen.findByTestId('agent-detail')).toBeInTheDocument();
    expect(screen.getByTestId('profile-builder')).toHaveTextContent('New Agent');
});

test('inline delete needs two clicks and does not open the detail', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    const row = screen.getByText('Researcher').closest('tr');
    const del = within(row).getByTestId('agent-delete');
    fireEvent.click(del); // arms — must not delete or navigate
    expect(profilesHook.deleteProfile).not.toHaveBeenCalled();
    expect(screen.queryByTestId('agent-detail')).not.toBeInTheDocument();

    fireEvent.click(del); // confirms
    await waitFor(() => expect(profilesHook.deleteProfile).toHaveBeenCalledWith('p1'));
    expect(screen.queryByTestId('agent-detail')).not.toBeInTheDocument();
});

test('a delete blocked by a routine surfaces a toast', async () => {
    profilesHook.deleteProfile.mockResolvedValue({
        conflict: true,
        usage: [{ routine_id: 'g1', routine_description: 'Daily digest' }],
    });
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    const row = screen.getByText('Researcher').closest('tr');
    const del = within(row).getByTestId('agent-delete');
    fireEvent.click(del);
    fireEvent.click(del);

    expect(await screen.findByText(/used by 1 routine/)).toBeInTheDocument();
});

test('row Duplicate calls duplicateProfile and stays on the list', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    const row = screen.getByText('Researcher').closest('tr');
    fireEvent.click(within(row).getByTestId('agent-duplicate'));

    await waitFor(() => expect(profilesHook.duplicateProfile).toHaveBeenCalledWith('p1'));
    expect(screen.queryByTestId('agent-detail')).not.toBeInTheDocument();
});

test('leaving with unsaved edits warns; Discard returns to the list', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Researcher'));
    await screen.findByTestId('agent-detail');
    fireEvent.click(screen.getByTestId('mock-edit')); // become dirty

    fireEvent.click(screen.getByTestId('agent-detail-back'));
    // Guard shows instead of navigating away.
    expect(screen.getByTestId('agent-unsaved-warning')).toBeInTheDocument();
    expect(screen.queryByTestId('agents-list')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('agent-unsaved-discard'));
    await waitFor(() => expect(screen.getByTestId('agents-list')).toBeInTheDocument());
});

test('unsaved warning can be dismissed to keep editing', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Researcher'));
    await screen.findByTestId('agent-detail');
    fireEvent.click(screen.getByTestId('mock-edit'));
    fireEvent.click(screen.getByTestId('agent-detail-back'));

    fireEvent.click(screen.getByTestId('agent-unsaved-keep'));
    expect(screen.queryByTestId('agent-unsaved-warning')).not.toBeInTheDocument();
    expect(screen.getByTestId('agent-detail')).toBeInTheDocument();
});

test('leaving a clean editor returns to the list without a warning', async () => {
    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Researcher'));
    await screen.findByTestId('agent-detail');
    fireEvent.click(screen.getByTestId('agent-detail-back'));

    expect(screen.queryByTestId('agent-unsaved-warning')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('agents-list')).toBeInTheDocument());
});

test('importing a pack merges the returned records and toasts a summary', async () => {
    // A profile pack that also carries a skill: both lists should take the
    // freshly created records straight from the response, no refetch.
    const imported = {
        profiles: [{ id: 'np', name: 'Imported Agent' }],
        skills: [{ id: 'ns', name: 'Imported Skill' }],
    };
    importPackFile.mockResolvedValue({ ok: true, data: imported });

    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    const file = new File(['{}'], 'x.agent.omnideck.json');
    fireEvent.change(screen.getByTestId('agents-import-input'), { target: { files: [file] } });

    await waitFor(() => expect(profilesHook.addProfiles).toHaveBeenCalledWith(imported.profiles));
    expect(skillsHook.addSkills).toHaveBeenCalledWith(imported.skills);
    expect(await screen.findByText('Imported 1 agent and 1 skill.')).toBeInTheDocument();
});

test('a failed import toasts the error and touches neither list', async () => {
    importPackFile.mockResolvedValue({ ok: false, error: 'Not a valid omnideck export file' });

    renderView();
    await waitFor(() => expect(screen.getByText('Researcher')).toBeInTheDocument());

    const file = new File(['nope'], 'x.agent.omnideck.json');
    fireEvent.change(screen.getByTestId('agents-import-input'), { target: { files: [file] } });

    expect(await screen.findByText('Not a valid omnideck export file')).toBeInTheDocument();
    expect(profilesHook.addProfiles).not.toHaveBeenCalled();
    expect(skillsHook.addSkills).not.toHaveBeenCalled();
});
