import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import WorkspacePane from '../WorkspacePane.jsx';
import CustomAppHost from '../apps/CustomAppHost.jsx';

const APP = { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' };
const TABS = [{ id: 'app:text-lab', label: 'Text Lab', icon: <i /> }];

function content() {
    return <CustomAppHost app={APP} active onOpenChat={vi.fn()} onComposeChat={vi.fn()} />;
}

test('changes a mounted child from full-space to a tabbed split pane without remounting it', () => {
    const props = {
        visible: true,
        tabs: TABS,
        activeTab: 'app:text-lab',
        onTabChange: vi.fn(),
        onCloseTab: vi.fn(),
        toolbar: <div data-testid="workspace-toolbar" />,
    };
    const { rerender } = render(
        <WorkspacePane {...props} layout="full">{content()}</WorkspacePane>,
    );
    const frame = screen.getByTestId('custom-app-frame');
    expect(screen.getByTestId('workspace-toolbar')).toBeInTheDocument();
    expect(screen.queryByTestId('preview-tab-bar')).not.toBeInTheDocument();

    rerender(<WorkspacePane {...props} layout="split">{content()}</WorkspacePane>);
    expect(screen.getByTestId('custom-app-frame')).toBe(frame);
    expect(screen.queryByTestId('workspace-toolbar')).not.toBeInTheDocument();
    expect(screen.getByTestId('preview-tab-app:text-lab')).toBeInTheDocument();
});

test('can stay mounted while another shell view hides it', () => {
    const { rerender } = render(
        <WorkspacePane
            visible
            layout="split"
            tabs={TABS}
            activeTab="app:text-lab"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        >
            {content()}
        </WorkspacePane>,
    );
    const frame = screen.getByTestId('custom-app-frame');

    rerender(
        <WorkspacePane
            visible={false}
            layout="split"
            tabs={TABS}
            activeTab="app:text-lab"
            onTabChange={vi.fn()}
            onCloseTab={vi.fn()}
        >
            {content()}
        </WorkspacePane>,
    );
    expect(screen.getByTestId('workspace-pane')).toHaveAttribute('data-visible', 'false');
    expect(screen.getByTestId('custom-app-frame')).toBe(frame);
});
