import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import BrowserSaveModal from '../BrowserSaveModal.jsx';
import { BrowserProfilesCatalogProvider } from '../BrowserProfilesContext.jsx';
import useBrowserProfiles from '../useBrowserProfiles.js';

const mocks = vi.hoisted(() => ({
    listBrowserProfiles: vi.fn(),
    previewBrowserState: vi.fn(),
    saveBrowserState: vi.fn(),
}));

vi.mock('../browserApi.js', () => ({
    listBrowserProfiles: mocks.listBrowserProfiles,
    previewBrowserState: mocks.previewBrowserState,
    saveBrowserState: mocks.saveBrowserState,
}));

const DEFAULT = {
    id: 'default',
    name: 'Default',
    icon: 'bi-globe2',
    sites: [],
};

function BrowserProfilesTestProvider({ children }) {
    const catalog = useBrowserProfiles();
    return (
        <BrowserProfilesCatalogProvider value={catalog}>
            {children}
        </BrowserProfilesCatalogProvider>
    );
}

function renderModal(props) {
    return render(<BrowserSaveModal {...props} />, { wrapper: BrowserProfilesTestProvider });
}

describe('BrowserSaveModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.listBrowserProfiles.mockResolvedValue([DEFAULT]);
        mocks.previewBrowserState.mockResolvedValue({
            preview_token: 'preview-1',
            source_profile_id: 'default',
            sites: [
                { domain: 'github.com', cookies: 4, local_storage: true, indexed_db: false },
            ],
        });
        mocks.saveBrowserState.mockResolvedValue({
            profile: { ...DEFAULT, name: 'Work accounts' },
            assigned_to_agent: false,
        });
    });

    it('does not render fallback save options while the Browser preview is loading', async () => {
        let resolveProfiles;
        let resolvePreview;
        mocks.listBrowserProfiles.mockReturnValue(new Promise((resolve) => {
            resolveProfiles = resolve;
        }));
        mocks.previewBrowserState.mockReturnValue(new Promise((resolve) => {
            resolvePreview = resolve;
        }));

        renderModal({ conversationId: 'conversation-1', onClose: vi.fn() });

        expect(screen.getByRole('status')).toHaveTextContent('Reading current Browser…');
        expect(screen.queryByTestId('browser-save-target')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('Profile name')).not.toBeInTheDocument();
        expect(screen.queryByTestId('browser-save-confirm')).not.toBeInTheDocument();

        resolveProfiles([DEFAULT]);
        resolvePreview({
            preview_token: 'preview-default',
            source_profile_id: 'default',
            agent_name: 'Default agent',
            sites: [],
        });

        const target = await screen.findByTestId('browser-save-target');
        expect(target).toHaveAttribute('data-value', 'default');
        expect(screen.queryByLabelText('Profile name')).not.toBeInTheDocument();
        expect(screen.getByTestId('browser-save-confirm')).toHaveTextContent('Update Default');
    });

    it('describes prospective data and updates the loaded profile by default', async () => {
        const user = userEvent.setup();
        const onClose = vi.fn();
        renderModal({ onClose });

        expect(await screen.findByText('Sites that will be saved')).toBeInTheDocument();
        expect(screen.getByText('github.com')).toBeInTheDocument();
        expect(screen.getByText('Create a reusable snapshot of this Browser for agents.')).toBeInTheDocument();
        expect(screen.queryByText(/Your Browser will not change/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Your sign-ins and site data/i)).not.toBeInTheDocument();
        expect(screen.getByText(/access any sites you are logged into/i)).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Update Default' }));

        await waitFor(() => expect(mocks.saveBrowserState).toHaveBeenCalledWith({
            conversationId: null,
            profileId: 'default',
            name: '',
            icon: 'bi-globe2',
            assignToAgent: false,
            previewToken: 'preview-1',
        }));
        expect(onClose).toHaveBeenCalledOnce();
    });

    it('requires a name and uses the shared icon picker when creating a profile', async () => {
        const user = userEvent.setup();
        renderModal({ onClose: vi.fn() });

        await screen.findByText('github.com');
        await user.click(screen.getByTestId('browser-save-target'));
        await user.click(screen.getByRole('option', { name: 'Create new profile' }));
        const save = screen.getByTestId('browser-save-confirm');
        expect(save).toBeDisabled();

        await user.type(screen.getByLabelText('Profile name'), 'Work accounts');
        await user.click(screen.getByTestId('browser-icon-picker-trigger'));
        await user.click(screen.getByTestId('browser-icon-bi-briefcase'));
        await user.click(save);

        await waitFor(() => expect(mocks.saveBrowserState).toHaveBeenCalledWith({
            conversationId: null,
            profileId: null,
            name: 'Work accounts',
            icon: 'bi-briefcase',
            assignToAgent: false,
            previewToken: 'preview-1',
        }));
    });

    it('only allows a new profile when takeover started from Empty', async () => {
        mocks.previewBrowserState.mockResolvedValue({
            preview_token: 'preview-empty',
            source_profile_id: null,
            agent_name: 'Empty agent',
            sites: [],
        });
        renderModal({ conversationId: 'conversation-1', onClose: vi.fn() });

        const target = await screen.findByTestId('browser-save-target');
        await userEvent.setup().click(target);
        expect(screen.getByRole('option', { name: 'Create new profile' })).toBeInTheDocument();
        expect(screen.queryByRole('option', { name: 'Update Default' })).not.toBeInTheDocument();
        expect(screen.getByText('Use this profile for Empty agent next time')).toBeInTheDocument();
    });

    it('only allows the actual source profile to be updated during takeover', async () => {
        const work = { ...DEFAULT, id: 'work', name: 'Work' };
        mocks.listBrowserProfiles.mockResolvedValue([DEFAULT, work]);
        mocks.previewBrowserState.mockResolvedValue({
            preview_token: 'preview-work',
            source_profile_id: 'work',
            agent_name: 'Work agent',
            sites: [],
        });
        renderModal({ conversationId: 'conversation-1', onClose: vi.fn() });

        const target = await screen.findByTestId('browser-save-target');
        expect(target).toHaveAttribute('data-value', 'work');
        await userEvent.setup().click(target);
        expect(screen.getByRole('option', { name: 'Update Work' })).toBeInTheDocument();
        expect(screen.queryByRole('option', { name: 'Update Default' })).not.toBeInTheDocument();
    });

    it('does not allow saving when the Browser preview could not be captured', async () => {
        mocks.previewBrowserState.mockRejectedValue(new Error('Preview failed'));
        renderModal({ onClose: vi.fn() });

        expect(await screen.findByText('Preview failed')).toBeInTheDocument();
        expect(screen.queryByTestId('browser-save-target')).not.toBeInTheDocument();
        expect(screen.queryByTestId('browser-save-confirm')).not.toBeInTheDocument();
        expect(mocks.saveBrowserState).not.toHaveBeenCalled();
    });
});
