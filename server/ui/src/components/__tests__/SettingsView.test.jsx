import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SettingsView from '../SettingsView.jsx';

vi.mock('../../contexts/AppData.jsx', () => ({ useAppData: () => ({ features: {} }) }));
vi.mock('../skills/SkillsTab.jsx', () => ({ default: ({ onOpenIntegration }) => {
    const [name, setName] = useState('Draft');
    return <><input aria-label="Skill draft" value={name} onChange={e => setName(e.target.value)} /><button onClick={() => onOpenIntegration('work')}>Review in Integrations</button></>;
} }));
vi.mock('../../features/integrations/IntegrationsTab.jsx', () => ({ default: ({ initialConnectionId }) => <div data-testid="integration-target">{initialConnectionId}</div> }));

describe('Settings integration links', () => {
    it('preserves the skill draft while visiting its integration', async () => {
        const user = userEvent.setup();
        render(<SettingsView />);
        await user.type(screen.getByRole('textbox', { name: 'Skill draft' }), ' edited');
        await user.click(screen.getByRole('button', { name: 'Review in Integrations' }));
        expect(screen.getByTestId('integration-target')).toHaveTextContent('work');
        expect(screen.queryByRole('textbox', { name: 'Skill draft' })).not.toBeInTheDocument();
        await user.click(screen.getByRole('tab', { name: 'Skills' }));
        expect(screen.getByRole('textbox', { name: 'Skill draft' })).toHaveValue('Draft edited');
    });
});
