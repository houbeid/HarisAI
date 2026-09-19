import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { reportsApi } from '../../api/reportsApi';
import { Table, type TableColumn } from '../ui/Table';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { decisionLabel, decisionTone } from '../../utils/decisionCasing';
import { fraudTypeLabel } from '../../utils/fraudTypeLabels';
import { formatRelativeTime } from '../../utils/formatRelativeTime';
import type { StrReportItem } from '../../types/reports';

const PAGE_SIZE = 20;

export function ReportTable() {
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ['reports', page],
    queryFn: () => reportsApi.getReports({ page, pageSize: PAGE_SIZE }),
  });

  const reports = query.data?.reports ?? [];
  // POINT OUVERT : ReportsResponse n'expose aucun total (ni totalCount ni
  // totalPages). Heuristique assumée : si la page reçue est plus courte
  // que PAGE_SIZE, on suppose qu'il n'y a rien après — pas une garantie,
  // mais évite d'afficher un bouton "Suivant" qui mène systématiquement
  // à une page vide. Un vrai champ de total côté backend réglerait ça
  // proprement.
  const hasNextPage = reports.length === PAGE_SIZE;

  const columns: TableColumn<StrReportItem>[] = [
    {
      header: 'Rapport',
      render: (r) => (
        <div>
          <div className="font-semibold text-gray-900">{r.reportId}</div>
          <div className="text-xs text-gray-500">{r.transactionId}</div>
        </div>
      ),
    },
    {
      header: 'Type / Décision',
      render: (r) => (
        <div>
          <div className="mb-1">{fraudTypeLabel(r.fraudType)}</div>
          <Badge tone={decisionTone(r.decision)}>{decisionLabel(r.decision)}</Badge>
        </div>
      ),
    },
    { header: 'Score', render: (r) => <span className="font-semibold">{r.riskScore}</span> },
    {
      header: 'Agent & note',
      render: (r) => (
        <div>
          {/* confirmedBy est une chaîne brute (probablement un email) —
              voir POINT OUVERT dans types/reports.ts : pas de nom lisible
              tant qu'un annuaire agents n'existe pas côté backend. */}
          <div className="font-medium text-gray-900">{r.confirmedBy}</div>
          {r.agentNote && <div className="text-xs text-gray-500">{r.agentNote}</div>}
        </div>
      ),
    },
    { header: 'Généré le', render: (r) => formatRelativeTime(r.generatedAt) },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">Rapports STR</h1>
      <p className="mb-4 mt-1 text-sm text-gray-500">
        Historique en lecture seule des signalements générés après confirmation d'une fraude —
        aucune action possible.
      </p>

      {query.isLoading ? (
        <p className="text-sm text-gray-500">Chargement…</p>
      ) : (
        <Table
          columns={columns}
          rows={reports}
          rowKey={(r) => r.reportId}
          emptyState={<p className="text-center text-gray-500">Aucun rapport pour l'instant.</p>}
        />
      )}

      <div className="mt-4 flex items-center justify-between">
        <span className="text-sm text-gray-500">Page {page}</span>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setPage((p) => p - 1)} disabled={page <= 1}>
            ← Précédent
          </Button>
          <Button variant="secondary" onClick={() => setPage((p) => p + 1)} disabled={!hasNextPage}>
            Suivant →
          </Button>
        </div>
      </div>
    </div>
  );
}
