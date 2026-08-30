import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import BrowserProfilesSettings from '../BrowserProfilesSettings.jsx';
import { BrowserProfilesCatalogProvider } from '../BrowserProfilesContext.jsx';
import useBrowserProfiles from '../useBrowserProfiles.js';

const mocks = vi.hoisted(() => ({
    clearBrowserProfileState: vi.fn(),
    deleteBrowserProfile: vi.fn(),
    listBrowserProfiles: vi.fn(),
    openBrowser: vi.fn(),
    removeBrowserProfileSites: vi.fn(),
    updateBrowserProfile: vi.fn(),
}));

vi.mock('../../navigation/DesktopNavigation.jsx', () => ({
    useDesktopNavigationCommands: () => ({ openBrowser: mocks.openBrowser }),
}));

vi.mock('../browserApi.js', () => ({
    clearBrowserProfileState: mocks.clearBrowserProfileState,
    deleteBrowserProfile: mocks.deleteBrowserProfile,
    listBrowserProfiles: mocks.listBrowserProfiles,
    removeBrowserProfileSites: mocks.removeBrowserProfileSites,
    updateBrowserProfile: mocks.updateBrowserProfile,
}));

const DEFAULT = {
    id: 'default',
    name: 'Default',
    icon: 'bi-globe2',
    updated_at: '2026-08-25T22:41:00Z',
    sites: [
        { domain: 'github.com', cookies: 4, local_storage: true, indexed_db: false },
        { domain: 'google.com', cookies: 2, local_storage: true, indexed_db: true },
        { domain: 'mail.google.com', cookies: 1, local_storage: true, indexed_db: false },
        { domain: 'notion.so', cookies: 3, local_storage: true, indexed_db: true },
        { domain: 'slack.com', cookies: 2, local_storage: false, indexed_db: false },
        { domain: 'stripe.com', cookies: 1, local_storage: false, indexed_db: false },
        { domain: 'zoom.us', cookies: 1, local_storage: false, indexed_db: false },
        { domain: 'figma.com', cookies: 2, local_storage: true, indexed_db: false },
    ],
};

const LINKEDIN = {
    id: 'linkedin',
    name: 'LinkedIn',
    icon: 'bi-linkedin',
    updated_at: '2026-08-26T13:16:00Z',
    sites: [{ domain: 'linkedin.com', cookies: 5, local_storage: true, indexed_db: false }],
};

let profilesCatalog;

function BrowserProfilesTestProvider({ children }) {
    profilesCatalog = useBrowserProfiles();
    return (
        <BrowserProfilesCatalogProvider value={profilesCatalog}>
            {children}
        </BrowserProfilesCatalogProvider>
    );
}

function renderSettings() {
    return render(<BrowserProfilesSettings />, { wrapper: BrowserProfilesTestProvider });
}

describe('BrowserProfilesSettings', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.listBrowserProfiles.mockResolvedValue([DEFAULT, LINKEDIN]);
        mocks.deleteBrowserProfile.mockResolvedValue(undefined);
        mocks.clearBrowserProfileState.mockResolvedValue({ ...DEFAULT, sites: [] });
        mocks.removeBrowserProfileSites.mockImplementation(async (id, domains) => ({
            ...DEFAULT,
            id,
            sites: DEFAULT.sites.filter((site) => !domains.includes(site.domain)),
        }));
        mocks.updateBrowserProfile.mockImplementation(async (id, updates) => ({
            ...(id === DEFAULT.id ? DEFAULT : LINKEDIN),
            ...updates,
        }));
    });

    it('uses a profile list and keeps site inventory in the selected detail pane', async () => {
        renderSettings();

        const defaultRow = await screen.findByTestId('browser-profile-default');
        expect(within(defaultRow).getByText('7 sites')).toBeInTheDocument();
        expect(within(defaultRow).queryByText('github.com')).not.toBeInTheDocument();
        expect(await screen.findByText('github.com')).toBeInTheDocument();
        expect(screen.getByText('2 domains · 3 cookies · Local storage · IndexedDB')).toBeInTheDocument();

        expect(screen.getByText('1–6 of 7')).toBeInTheDocument();
        expect(screen.queryByText('zoom.us')).not.toBeInTheDocument();
        await userEvent.setup().click(screen.getByRole('button', { name: 'Next sites page' }));
        expect(screen.getByText('zoom.us')).toBeInTheDocument();

        const siteSearch = screen.getByRole('searchbox', { name: 'Search sites in profile' });
        await userEvent.setup().type(siteSearch, 'notion');
        expect(screen.getByText('notion.so')).toBeInTheDocument();
        expect(screen.queryByText('github.com')).not.toBeInTheDocument();
    });

    it('renames and changes the icon of the selected profile', async () => {
        const user = userEvent.setup();
        renderSettings();

        await user.click(await screen.findByRole('button', { name: 'Open LinkedIn' }));
        const name = screen.getByLabelText('Name');
        await user.clear(name);
        await user.type(name, 'Client social');
        await user.click(screen.getByTestId('browser-icon-picker-trigger'));
        await user.click(screen.getByTestId('browser-icon-bi-google'));
        await user.click(screen.getByRole('button', { name: 'Save' }));

        await waitFor(() => expect(mocks.updateBrowserProfile).toHaveBeenCalledWith('linkedin', {
            name: 'Client social',
            icon: 'bi-google',
        }));
        expect(screen.getByRole('button', { name: 'Open Client social' })).toBeInTheDocument();
    });

    it('uses two-click confirmation before deleting a non-default profile', async () => {
        const user = userEvent.setup();
        renderSettings();

        await user.click(await screen.findByRole('button', { name: 'Open LinkedIn' }));
        const remove = screen.getByTestId('browser-profile-delete');
        await user.click(remove);
        expect(mocks.deleteBrowserProfile).not.toHaveBeenCalled();
        expect(remove).toHaveTextContent('Delete profile?');
        await user.click(remove);

        await waitFor(() => expect(mocks.deleteBrowserProfile).toHaveBeenCalledWith('linkedin'));
        expect(screen.queryByRole('button', { name: 'Open LinkedIn' })).not.toBeInTheDocument();
        expect(screen.queryByTestId('browser-profile-delete')).not.toBeInTheDocument();
    });

    it('names the agents preventing a profile from being deleted', async () => {
        const user = userEvent.setup();
        const conflict = new Error('This browser profile is assigned to an agent');
        conflict.details = { agents: ['Recruiting', 'LinkedIn Outreach'] };
        mocks.deleteBrowserProfile.mockRejectedValue(conflict);
        renderSettings();

        await user.click(await screen.findByRole('button', { name: 'Open LinkedIn' }));
        const remove = screen.getByTestId('browser-profile-delete');
        await user.click(remove);
        await user.click(remove);

        expect(await screen.findByText("Can't delete — profile is in use")).toBeInTheDocument();
        expect(screen.getByText(
            'Used by 2 agents. Assign them another Browser profile or Empty, then try again.',
        )).toBeInTheDocument();
        expect(screen.getByText('Agents: Recruiting · LinkedIn Outreach')).toBeInTheDocument();
        expect(within(screen.getByRole('alert')).queryByRole('list')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Open LinkedIn' })).toBeInTheDocument();
    });

    it('opens Browser with a request to load the selected profile', async () => {
        const user = userEvent.setup();
        renderSettings();
        await screen.findByTestId('browser-profile-default');

        await user.click(screen.getByRole('button', { name: 'Open in Browser' }));
        expect(mocks.openBrowser).toHaveBeenCalledWith('default', 'Default');
    });

    it('keeps unsaved identity edits when profile data changes elsewhere', async () => {
        const user = userEvent.setup();
        renderSettings();

        await user.click(await screen.findByRole('button', { name: 'Open LinkedIn' }));
        const name = screen.getByLabelText('Name');
        await user.clear(name);
        await user.type(name, 'Unsaved name');

        act(() => {
            profilesCatalog.upsertProfile({
                ...LINKEDIN,
                sites: [{ domain: 'linkedin.com', cookies: 6, local_storage: true, indexed_db: false }],
            });
        });

        expect(name).toHaveValue('Unsaved name');
    });

    it('removes every exact domain represented by one grouped site row', async () => {
        const user = userEvent.setup();
        renderSettings();
        await screen.findByText('google.com');

        const remove = screen.getByRole('button', {
            name: 'Remove google.com from this profile',
        });
        await user.click(remove);
        expect(mocks.removeBrowserProfileSites).not.toHaveBeenCalled();
        expect(screen.getByRole('dialog', { name: 'Remove google.com?' })).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Remove site' }));

        await waitFor(() => expect(mocks.removeBrowserProfileSites).toHaveBeenCalledWith(
            'default',
            ['google.com', 'mail.google.com'],
        ));
        expect(screen.queryByText('google.com')).not.toBeInTheDocument();
        expect(screen.getByText('github.com')).toBeInTheDocument();
    });

    it('clears all state without deleting the profile', async () => {
        const user = userEvent.setup();
        renderSettings();
        await screen.findByText('github.com');

        const clear = screen.getByTestId('browser-profile-clear-state');
        await user.click(clear);
        expect(mocks.clearBrowserProfileState).not.toHaveBeenCalled();
        expect(clear).toHaveAccessibleName('Clear all state?');
        await user.click(clear);

        await waitFor(() => expect(mocks.clearBrowserProfileState).toHaveBeenCalledWith('default'));
        expect(screen.getByText('No site data saved in this profile.')).toBeInTheDocument();
        expect(screen.getByTestId('browser-profile-default')).toHaveTextContent('0 sites');
        expect(screen.getByTestId('browser-profile-clear-state')).toBeDisabled();
    });
});
