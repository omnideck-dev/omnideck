import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import BrowserView from '../BrowserView.jsx';
import { BrowserProfilesCatalogProvider } from '../BrowserProfilesContext.jsx';
import useBrowserProfiles from '../useBrowserProfiles.js';

const mocks = vi.hoisted(() => ({
    clearProfileLoadRequest: vi.fn(),
    getBrowserSession: vi.fn(),
    listBrowserProfiles: vi.fn(),
    loadBrowserSession: vi.fn(),
    openSettings: vi.fn(),
    profileLoadRequest: null,
    saveModalProps: vi.fn(),
}));

vi.mock('../../navigation/DesktopNavigation.jsx', () => ({
    useDesktopNavigationCommands: () => ({
        openSettings: mocks.openSettings,
    }),
}));

vi.mock('../BrowserProfileLoadRequest.jsx', () => ({
    useBrowserProfileLoadRequest: () => ({
        request: mocks.profileLoadRequest,
        clearRequest: mocks.clearProfileLoadRequest,
    }),
}));

vi.mock('../useBrowserControl.js', () => ({
    default: () => ({
        liveTabs: [{ id: 'browser-tab', url: 'about:blank', title: 'Untitled' }],
        engaged: true,
        navUrl: 'about:blank',
        navTitle: 'Untitled',
    }),
}));

vi.mock('../browserApi.js', () => ({
    getBrowserSession: mocks.getBrowserSession,
    listBrowserProfiles: mocks.listBrowserProfiles,
    loadBrowserSession: mocks.loadBrowserSession,
}));

vi.mock('../BrowserSaveModal.jsx', () => ({
    default: (props) => {
        mocks.saveModalProps(props);
        return <div data-testid="mock-browser-save-modal" />;
    },
}));

const SESSION = {
    browser_profile_id: 'default',
    profiles: [
        { id: 'default', name: 'Default' },
        { id: 'linkedin', name: 'LinkedIn' },
    ],
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

function renderBrowserView() {
    return render(<BrowserView />, { wrapper: BrowserProfilesTestProvider });
}

describe('BrowserView profile load requests', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.getBrowserSession.mockResolvedValue(SESSION);
        mocks.listBrowserProfiles.mockResolvedValue(SESSION.profiles);
        mocks.loadBrowserSession.mockResolvedValue({
            ...SESSION,
            browser_profile_id: 'linkedin',
        });
        mocks.profileLoadRequest = {
            profileId: 'linkedin',
            profileName: 'Client social',
        };
        mocks.clearProfileLoadRequest.mockImplementation(() => {
            mocks.profileLoadRequest = null;
        });
    });

    it('confirms and loads a profile requested from profile settings', async () => {
        const user = userEvent.setup();
        await act(async () => {
            renderBrowserView();
        });

        expect(await screen.findByRole('heading', { name: 'Load Client social?' })).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Load profile' }));

        await waitFor(() => expect(mocks.loadBrowserSession).toHaveBeenCalledWith('linkedin'));
        expect(mocks.clearProfileLoadRequest).toHaveBeenCalledOnce();
    });

    it('shows progress and prevents dismissal while replacing the Browser', async () => {
        let finishLoading;
        mocks.loadBrowserSession.mockImplementation(() => new Promise((resolve) => {
            finishLoading = resolve;
        }));
        const user = userEvent.setup();
        await act(async () => {
            renderBrowserView();
        });

        await user.click(await screen.findByRole('button', { name: 'Load profile' }));

        const loadingButton = screen.getByRole('button', { name: 'Loading…' });
        expect(loadingButton).toBeDisabled();
        expect(loadingButton).toHaveAttribute('aria-busy', 'true');
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();

        await user.keyboard('{Escape}');
        expect(screen.getByTestId('replace-browser-modal')).toBeInTheDocument();

        await act(async () => {
            finishLoading({
                ...SESSION,
                browser_profile_id: 'linkedin',
            });
        });

        expect(screen.queryByTestId('replace-browser-modal')).not.toBeInTheDocument();
    });

    it('clears a canceled profile request before Browser remounts', async () => {
        const user = userEvent.setup();
        let rendered;
        await act(async () => {
            rendered = renderBrowserView();
        });

        expect(await screen.findByRole('heading', { name: 'Load Client social?' })).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Cancel' }));

        expect(mocks.clearProfileLoadRequest).toHaveBeenCalledOnce();
        expect(screen.queryByRole('heading', { name: 'Load Client social?' })).not.toBeInTheDocument();

        rendered.unmount();
        await act(async () => {
            renderBrowserView();
        });

        await waitFor(() => expect(mocks.getBrowserSession).toHaveBeenCalledTimes(2));
        expect(screen.queryByRole('heading', { name: 'Load Client social?' })).not.toBeInTheDocument();
    });

    it('does not prompt when the current profile is selected again', async () => {
        mocks.profileLoadRequest = null;
        const user = userEvent.setup();
        await act(async () => {
            renderBrowserView();
        });

        const profileSelect = await screen.findByTestId('browser-profile-select');
        expect(profileSelect).toHaveAttribute('data-value', 'default');
        await user.click(profileSelect);
        await user.click(screen.getByRole('menuitemradio', { name: 'Default' }));

        expect(screen.queryByTestId('replace-browser-modal')).not.toBeInTheDocument();
        expect(mocks.loadBrowserSession).not.toHaveBeenCalled();
    });

    it('gives the save modal the profile already loaded in the root Browser', async () => {
        mocks.profileLoadRequest = null;
        const user = userEvent.setup();
        await act(async () => {
            renderBrowserView();
        });

        await user.click(await screen.findByTestId('browser-save-state'));

        expect(screen.getByTestId('mock-browser-save-modal')).toBeInTheDocument();
        expect(mocks.saveModalProps).toHaveBeenLastCalledWith(expect.objectContaining({
            loadedProfile: SESSION.profiles[0],
        }));
    });

    it('ignores an open-in-Browser request for the profile already loaded', async () => {
        mocks.profileLoadRequest = {
            profileId: 'default',
            profileName: 'Default',
        };
        await act(async () => {
            renderBrowserView();
        });

        await waitFor(() => expect(mocks.clearProfileLoadRequest).toHaveBeenCalledOnce());
        expect(screen.queryByTestId('replace-browser-modal')).not.toBeInTheDocument();
    });
});
