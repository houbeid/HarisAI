import type { ReactNode } from 'react';

/**
 * Générique par design : ne connaît ni Alert ni StrReportItem. Consommé
 * par les composants métier via une définition de colonnes — c'est le
 * même composant qui rendra le tableau Alertes ET le tableau Rapports STR,
 * cohérent avec la densité "outil bancaire pro" tranchée dans le brief.
 */
export interface TableColumn<T> {
  header: string;
  // Champ pour React key — pas d'index de tableau, pour un rendu stable
  // même si la liste se réordonne au rafraîchissement périodique.
  render: (row: T) => ReactNode;
  widthClassName?: string;
}

interface TableProps<T> {
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  // Rendu optionnel d'un indicateur visuel par ligne (ex: la bordure
  // colorée à gauche de chaque ligne, visible sur la maquette, dérivée
  // de la sévérité) — passé par le composant métier, jamais calculé ici.
  rowAccentClassName?: (row: T) => string;
  emptyState?: ReactNode;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  rowAccentClassName,
  emptyState,
}: TableProps<T>) {
  if (rows.length === 0 && emptyState) {
    return <div className="rounded-lg border border-gray-200 bg-white p-12">{emptyState}</div>;
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-gray-200 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
          {columns.map((col) => (
            <th key={col.header} className={`px-4 py-2 ${col.widthClassName ?? ''}`}>
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            className={`border-b border-gray-100 ${onRowClick ? 'cursor-pointer hover:bg-gray-50' : ''} ${
              rowAccentClassName ? `border-l-2 ${rowAccentClassName(row)}` : ''
            }`}
          >
            {columns.map((col) => (
              <td key={col.header} className="px-4 py-3">
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
