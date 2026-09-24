import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import Button from '../Button.jsx';

describe('Button', () => {
    it('uses the standard busy treatment for loading actions', () => {
        render(
            <Button loading loadingLabel="Saving…">
                Save
            </Button>,
        );

        const button = screen.getByRole('button', { name: 'Saving…' });
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute('aria-busy', 'true');
        expect(screen.queryByText('Save')).not.toBeInTheDocument();
    });
});
