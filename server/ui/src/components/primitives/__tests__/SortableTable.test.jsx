import { render, screen, fireEvent } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import SortableTable from '../SortableTable.jsx';

const COLUMNS = [
    { key: 'name', header: 'Name', sortable: true, render: (r) => r.name },
    { key: 'age', header: 'Age', sortable: true, render: (r) => String(r.age) },
    { key: 'note', header: 'Note', render: (r) => r.note },
];

const ROWS = [
    { id: 'a', name: 'Alpha', age: 1, note: 'first' },
    { id: 'b', name: 'Beta', age: 2, note: 'second' },
];

function renderTable(props = {}) {
    return render(
        <SortableTable
            columns={COLUMNS}
            rows={ROWS}
            rowKey={(r) => r.id}
            sort={{ key: 'name', dir: 'asc' }}
            onSort={() => {}}
            rowTestId="row"
            testId="tbl"
            {...props}
        />,
    );
}

test('renders headers and a row per item', () => {
    renderTable();
    expect(screen.getByTestId('tbl')).toBeInTheDocument();
    ['Name', 'Age', 'Note'].forEach((h) => expect(screen.getByText(h)).toBeInTheDocument());
    expect(screen.getAllByTestId('row')).toHaveLength(2);
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('second')).toBeInTheDocument();
});

test('clicking a sortable header calls onSort; a non-sortable header does not', () => {
    const onSort = vi.fn();
    renderTable({ onSort });
    fireEvent.click(screen.getByText('Name'));
    expect(onSort).toHaveBeenCalledWith('name');
    fireEvent.click(screen.getByText('Note'));
    expect(onSort).toHaveBeenCalledTimes(1);
});

test('shows a directional caret on the active sort column only', () => {
    const { container, rerender } = renderTable({ sort: { key: 'age', dir: 'asc' } });
    expect(container.querySelector('.bi-caret-up-fill')).toBeTruthy();
    expect(container.querySelector('.bi-caret-down-fill')).toBeFalsy();

    rerender(
        <SortableTable
            columns={COLUMNS}
            rows={ROWS}
            rowKey={(r) => r.id}
            sort={{ key: 'age', dir: 'desc' }}
            onSort={() => {}}
        />,
    );
    expect(container.querySelector('.bi-caret-down-fill')).toBeTruthy();
    expect(container.querySelector('.bi-caret-up-fill')).toBeFalsy();
});

test('clicking a row calls onRowClick with that row', () => {
    const onRowClick = vi.fn();
    renderTable({ onRowClick });
    fireEvent.click(screen.getByText('Alpha'));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
});

test('marks the active row and applies a per-row class', () => {
    renderTable({ activeRowKey: 'b', rowClassName: (r) => (r.age > 1 ? 'big' : '') });
    const rowB = screen.getByText('Beta').closest('tr');
    expect(rowB.className).toContain('sel');
    expect(rowB.className).toContain('big');
    const rowA = screen.getByText('Alpha').closest('tr');
    expect(rowA.className).not.toContain('sel');
});

test('revealOnHover still renders the cell content', () => {
    const columns = [{ key: 'name', header: 'Name', revealOnHover: true, render: (r) => r.name }];
    render(<SortableTable columns={columns} rows={ROWS} rowKey={(r) => r.id} sort={{ key: 'name', dir: 'asc' }} onSort={() => {}} />);
    expect(screen.getByText('Alpha')).toBeInTheDocument();
});
