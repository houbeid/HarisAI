import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Table, type TableColumn } from '../../../src/components/ui/Table';

interface FakeRow {
  id: string;
  label: string;
}

const columns: TableColumn<FakeRow>[] = [{ header: 'Label', render: (row) => row.label }];

describe('Table', () => {
  it('affiche une ligne par élément, avec le bon en-tête de colonne', () => {
    const rows: FakeRow[] = [
      { id: '1', label: 'Première ligne' },
      { id: '2', label: 'Deuxième ligne' },
    ];
    render(<Table columns={columns} rows={rows} rowKey={(r) => r.id} />);

    expect(screen.getByText('Label')).toBeInTheDocument();
    expect(screen.getByText('Première ligne')).toBeInTheDocument();
    expect(screen.getByText('Deuxième ligne')).toBeInTheDocument();
  });

  it('appelle onRowClick avec la bonne ligne au clic', async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    const rows: FakeRow[] = [{ id: '1', label: 'Cliquable' }];
    render(<Table columns={columns} rows={rows} rowKey={(r) => r.id} onRowClick={onRowClick} />);

    await user.click(screen.getByText('Cliquable'));

    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
  });

  it('affiche emptyState quand rows est vide, pas un tableau vide', () => {
    render(
      <Table columns={columns} rows={[]} rowKey={(r) => r.id} emptyState={<p>Aucune donnée</p>} />,
    );

    expect(screen.getByText('Aucune donnée')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
