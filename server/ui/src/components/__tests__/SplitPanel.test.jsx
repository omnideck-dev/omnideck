import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';

import SplitPanel from '../SplitPanel.jsx';
import styles from '../SplitPanel.module.css';

it('owns the list and detail layout without consumer style overrides', () => {
    const children = <><SplitPanel.List>Accounts</SplitPanel.List><SplitPanel.Detail>Details</SplitPanel.Detail></>;
    render(<SplitPanel>{children}</SplitPanel>);
    const list = screen.getByText('Accounts');
    expect(list).toHaveClass(styles.list);
    expect(screen.getByText('Details')).toHaveClass(styles.detail);
    expect(list.parentElement).toHaveClass(styles.container);
});

it('aligns the title and optional actions in a shared list header', () => {
    render(<SplitPanel.Header actions={<button>Add</button>}>Providers · 2</SplitPanel.Header>);
    expect(screen.getByText('Providers · 2').parentElement).toHaveClass(styles.header);
    expect(screen.getByRole('button', { name: 'Add' }).parentElement).toHaveClass(styles.header);
});
