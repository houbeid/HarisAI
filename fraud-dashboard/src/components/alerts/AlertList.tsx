import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { alertsApi } from '../../api/alertsApi';
import { onReceiveAlert } from '../../realtime/alertHubClient';
import type { AlertListItem, AlertStatus } from '../../types/alerts';
import { Table, type TableColumn } from '../ui/Table';
import { Tabs } from '../ui/Tabs';
import { StatCard } from '../ui/StatCard';
import { Badge } from '../ui/Badge';
import { Toast } from '../ui/Toast';
import { decisionLabel, decisionTone } from '../../utils/decisionCasing';
import { fraudTypeLabel } from '../../utils/fraudTypeLabels';
import { alertStatusLabel, alertStatusTone } from '../../utils/alertStatusLabels';
import { formatRelativeTime } from '../../utils/formatRelativeTime';

/**
 * POINT OUVERT (voir décision prise avec Hamade) : GET /alerts n'expose
 * aucune valeur de `status` combinée pour "Traitées" (Confirmed+Dismissed
 * réunis), et AlertsResponse n'a pas de champ `totalProcessed`. Deux
 * conséquences assumées, pas des bugs :
 *  1. L'onglet "En attente" seul a une pagination réelle (status=Pending).
 *     "Traitées" et "Toutes" chargent une grande page (PROCESSED_PAGE_SIZE)
 *     sans navigation "page suivante".
 *  2. Le compteur "traitées" est DÉRIVÉ du nombre de lignes reçues, pas
 *     une vraie valeur serveur — affiché avec un "+" s'il atteint le
 *     plafond, pour ne jamais afficher un chiffre potentiellement faux
 *     comme s'il était exact.
 */
const PROCESSED_PAGE_SIZE = 100;

type TabValue = 'pending' | 'processed' | 'all';

const TAB_OPTIONS: { value: TabValue; label: string }[] = [
  { value: 'pending', label: 'En attente' },
  { value: 'processed', label: 'Traitées' },
  { value: 'all', label: 'Toutes' },
];

export function AlertList({ onSelectAlert }: { onSelectAlert: (alert: AlertListItem) => void }) {
  const [tab, setTab] = useState<TabValue>('pending');
  const [newAlertCount, setNewAlertCount] = useState(0);
  const queryClient = useQueryClient();

  const pendingQuery = useQuery({
    queryKey: ['alerts', 'Pending'],
    queryFn: () => alertsApi.getAlerts({ status: 'Pending', page: 1, pageSize: 50 }),
    // Rafraîchissement périodique : seule garantie de voir les alertes
    // créées par le Worker en arrière-plan, qui n'émettent jamais via
    // SignalR (NoOpAlertNotifier) — voir types/realtime.ts.
    refetchInterval: 30_000,
  });

  const processedQuery = useQuery({
    queryKey: ['alerts', 'processed-or-all'],
    queryFn: () => alertsApi.getAlerts({ page: 1, pageSize: PROCESSED_PAGE_SIZE }),
    refetchInterval: 30_000,
    // Toujours activée, même sur l'onglet "En attente" : le compteur
    // "traitées" affiché en haut de page en a besoin en permanence, pas
    // seulement quand l'agent bascule sur l'onglet correspondant.
  });

  // ---- Temps réel : incrémente un compteur de toast, ne modifie jamais
  // directement le cache react-query — la source de vérité reste le
  // prochain refetch (immédiat ici, via invalidateQueries).
  useEffect(() => {
    return onReceiveAlert(() => {
      setNewAlertCount((n) => n + 1);
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    });
  }, [queryClient]);

  const rows: AlertListItem[] = (() => {
    if (tab === 'pending') return pendingQuery.data?.alerts ?? [];
    const all = processedQuery.data?.alerts ?? [];
    return tab === 'processed' ? all.filter((a) => a.status !== 'Pending') : all;
  })();

  const pendingCount = pendingQuery.data?.totalPending ?? 0;
  const processedRows = processedQuery.data?.alerts ?? [];
  const processedCountRaw = processedRows.filter((a) => a.status !== 'Pending').length;
  const processedCountDisplay =
    processedRows.length >= PROCESSED_PAGE_SIZE ? `${processedCountRaw}+` : processedCountRaw;

  const columns: TableColumn<AlertListItem>[] = [
    {
      // POINT OUVERT : la maquette affiche un montant (ex: "185 000 MRU")
      // sous l'identifiant de transaction, mais AlertListItem (contrat
      // réel, FRONTEND_STARTER_PACK.md) n'expose aucun champ montant.
      // On affiche donc seulement transactionId + operator ici — ajouter
      // le montant nécessiterait d'abord que le backend l'expose.
      header: 'Transaction',
      render: (a) => (
        <div>
          <div className="font-semibold text-gray-900">{a.transactionId}</div>
          <div className="text-xs text-gray-500">{a.operator}</div>
        </div>
      ),
    },
    { header: 'Score', render: (a) => <span className="font-semibold">{a.score}</span> },
    {
      header: 'Décision',
      render: (a) => <Badge tone={decisionTone(a.decision)}>{decisionLabel(a.decision)}</Badge>,
    },
    { header: 'Type de fraude', render: (a) => fraudTypeLabel(a.fraudType) },
    {
      header: 'Statut',
      render: (a) => <Badge tone={alertStatusTone(a.status)}>{alertStatusLabel(a.status)}</Badge>,
    },
    { header: 'Créée', render: (a) => formatRelativeTime(a.createdAt) },
  ];

  const isLoading = tab === 'pending' ? pendingQuery.isLoading : processedQuery.isLoading;
  const lastUpdated =
    tab === 'pending' ? pendingQuery.dataUpdatedAt : processedQuery.dataUpdatedAt;

  return (
    <div>
      {newAlertCount > 0 && (
        <Toast
          message={`${newAlertCount} nouvelle${newAlertCount > 1 ? 's' : ''} alerte${
            newAlertCount > 1 ? 's' : ''
          } reçue${newAlertCount > 1 ? 's' : ''} en direct`}
          onDismiss={() => setNewAlertCount(0)}
        />
      )}

      <h1 className="text-2xl font-bold text-gray-900">Alertes de fraude</h1>
      {lastUpdated > 0 && (
        <p className="mt-1 text-sm text-gray-500">
          Dernière actualisation : {formatRelativeTime(new Date(lastUpdated).toISOString())} ·
          actualisation auto toutes les 30s
        </p>
      )}

      <div className="my-4 flex gap-4">
        <StatCard value={pendingCount} label="alertes en attente" />
        <StatCard value={processedCountDisplay} label="traitées" />
      </div>

      <Tabs options={TAB_OPTIONS} value={tab} onChange={setTab} />

      <div className="mt-4">
        {isLoading ? (
          <p className="text-sm text-gray-500">Chargement…</p>
        ) : (
          <Table
            columns={columns}
            rows={rows}
            rowKey={(a) => a.alertId}
            onRowClick={onSelectAlert}
            rowAccentClassName={(a) => {
              const tone = decisionTone(a.decision);
              return tone === 'danger'
                ? 'border-l-red-500'
                : tone === 'warning'
                  ? 'border-l-amber-500'
                  : 'border-l-green-500';
            }}
            emptyState={
              <div className="text-center">
                <p className="font-semibold text-gray-900">Aucune alerte à afficher</p>
                <p className="mt-1 text-sm text-gray-500">
                  Aucune alerte ne correspond à ce filtre pour le moment. La liste s'actualise
                  automatiquement.
                </p>
              </div>
            }
          />
        )}
      </div>
    </div>
  );
}
