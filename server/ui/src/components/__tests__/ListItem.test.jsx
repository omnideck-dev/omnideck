import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import ListItem from '../ListItem.jsx';
import styles from '../ListItem.module.css';

it('uses the shared selectable appearance and supports custom content', () => {
    render(<ListItem active><span>Browser profile</span></ListItem>);
    const row = screen.getByRole('button', { name: 'Browser profile' });
    expect(row).toHaveClass(styles.item, styles.active);
});

it('owns the card appearance and icon without consumer style overrides', () => {
    const onClick = vi.fn();
    render(<ListItem active icon={<i>mail</i>} name="Work account"
        description="2 tools selected" onClick={onClick} aria-current="true" />);
    const row = screen.getByRole('button', { name: 'Work account 2 tools selected' });
    expect(row).toHaveClass(styles.item, styles.active);
    expect(row).toHaveAttribute('aria-current', 'true');
    expect(screen.getByText('mail').parentElement).toHaveAttribute('aria-hidden', 'true');
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledOnce();
});

it('forwards disabled state and does not activate disabled cards', () => {
    const onClick = vi.fn();
    render(<ListItem name="Work account" disabled onClick={onClick} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).not.toHaveBeenCalled();
});
