import { useState } from 'react';
import { Drawer } from '../ui/Drawer';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { TextArea } from '../ui/TextArea';
import { alertsApi } from '../../api/alertsApi';
import { ApiError } from '../../api/httpClient';
import { decisionLabel, decisionTone } from '../../utils/decisionCasing';
import { fraudTypeLabel } from '../../utils/fraudTypeLabels';
import { alertStatusLabel, alertStatusTone } from '../../utils/alertStatusLabels';
import { formatRelativeTime } from '../../utils/formatRelativeTime';
import type { AlertListItem, AlertValidationAction, ValidateAlertResponse } from '../../types/alerts';

/**
 * POINT OUVERT MAJEUR : aucun GET /alerts/{id} n'existe dans le contrat.
 * Après un 409, on ne peut PAS relire fiablement les infos à jour de
 * cette alerte précise — seulement re-questionner GET /alerts (liste) et
 * espérer que l'alerte soit dans la fenêtre récupérée. Si elle ne l'est
 * pas (page suivante, filtre différent), on l'assume honnêtement plutôt
 * que d'afficher une fausse certitude — voir renderConflict ci-dessous.
 */
const CONFLICT_LOOKUP_PAGE_SIZE = 100;

interface AlertDetailPanelProps {
  alert: AlertListItem | null;
  onClose: () => void;
  onValidated: (result: ValidateAlertResponse) => void;
}

type SubmitState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'conflict'; reviewedBy: string | null; reviewedAt: string | null }
  | { kind: 'notFound' }
  | { kind: 'error'; message: string };

export function AlertDetailPanel({ alert, onClose, onValidated }: AlertDetailPanelProps) {
  const [action, setAction] = useState<AlertValidationAction | null>(null);
  const [note, setNote] = useState('');
  const [submitState, setSubmitState] = useState<SubmitState>({ kind: 'idle' });

  // Reset propre à chaque nouvelle alerte ouverte — pas de state d'une
  // alerte précédente qui fuite visuellement sur la suivante.
  const resetAndClose = () => {
    setAction(null);
    setNote('');
    setSubmitState({ kind: 'idle' });
    onClose();
  };

  if (!alert) return null;

  const isAlreadyProcessed = alert.status !== 'Pending';

  async function handleSubmit() {
    if (!action || !alert) return;
    setSubmitState({ kind: 'submitting' });
    try {
      const result = await alertsApi.validateAlert(alert.alertId, {
        action,
        note: note.trim() ? note.trim() : undefined,
      });
      onValidated(result);
      resetAndClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === 'alert_already_processed') {
        // Tentative de retrouver qui/quand — voir POINT OUVERT en tête de
        // fichier : peut échouer à retrouver l'alerte, géré honnêtement.
        try {
          const list = await alertsApi.getAlerts({ page: 1, pageSize: CONFLICT_LOOKUP_PAGE_SIZE });
          const found = list.alerts.find((a) => a.alertId === alert.alertId);
          setSubmitState({
            kind: 'conflict',
            reviewedBy: found?.reviewedBy ?? null,
            reviewedAt: found?.reviewedAt ?? null,
          });
        } catch {
          setSubmitState({ kind: 'conflict', reviewedBy: null, reviewedAt: null });
        }
      } else if (err instanceof ApiError && err.code === 'alert_not_found') {
        setSubmitState({ kind: 'notFound' });
      } else {
        setSubmitState({ kind: 'error', message: 'Une erreur est survenue. Réessayez.' });
      }
    }
  }

  return (
    <Drawer open={alert !== null} onClose={resetAndClose} title="Détail de l'alerte">
      {submitState.kind === 'conflict' && (
        <ConflictNotice reviewedBy={submitState.reviewedBy} reviewedAt={submitState.reviewedAt} onBack={resetAndClose} />
      )}

      {submitState.kind === 'notFound' && (
        <div className="text-center">
          <p className="mb-2 text-4xl">🔍</p>
          <p className="font-semibold text-gray-900">Alerte introuvable</p>
          <p className="mb-4 mt-1 text-sm text-gray-500">
            Cette alerte n'existe plus ou a été supprimée. Elle a peut-être déjà été archivée.
          </p>
          <Button onClick={resetAndClose}>Retour à la liste</Button>
        </div>
      )}

      {(submitState.kind === 'idle' || submitState.kind === 'submitting' || submitState.kind === 'error') && (
        <>
          <div className="mb-4 flex gap-2">
            <Badge tone={decisionTone(alert.decision)}>{decisionLabel(alert.decision)}</Badge>
            <Badge tone={alertStatusTone(alert.status)}>{alertStatusLabel(alert.status)}</Badge>
          </div>
          <h3 className="text-lg font-bold text-gray-900">{alert.transactionId}</h3>
          <p className="mb-4 text-sm text-gray-500">{formatRelativeTime(alert.createdAt)}</p>

          <div className="mb-4 grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-gray-50 p-3">
              <div className="text-xs uppercase text-gray-500">Score de fraude</div>
              <div className="text-2xl font-bold">{alert.score}/100</div>
            </div>
            <div className="rounded-lg bg-gray-50 p-3">
              <div className="text-xs uppercase text-gray-500">Type de fraude</div>
              <div className="font-semibold">{fraudTypeLabel(alert.fraudType)}</div>
            </div>
          </div>

          {isAlreadyProcessed ? (
            // Déjà traitée au moment où la liste a été chargée (pas un
            // conflit en cours, juste une consultation en lecture seule) —
            // reviewedBy/reviewedAt viennent directement de AlertListItem,
            // pas besoin d'un appel supplémentaire ici.
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
              Traitée{alert.reviewedBy ? ` par ${alert.reviewedBy}` : ''}
              {alert.reviewedAt ? ` — ${formatRelativeTime(alert.reviewedAt)}` : ''}.
            </div>
          ) : (
            <>
              <h4 className="mb-2 font-semibold text-gray-900">Décision de l'agent</h4>
              <div className="mb-4 flex gap-2">
                <Button
                  variant="secondary"
                  onClick={() => setAction('Confirm')}
                  className={action === 'Confirm' ? 'ring-2 ring-gray-900' : ''}
                  disabled={submitState.kind === 'submitting'}
                >
                  ✓ Confirmer la fraude
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setAction('Dismiss')}
                  className={action === 'Dismiss' ? 'ring-2 ring-gray-900' : ''}
                  disabled={submitState.kind === 'submitting'}
                >
                  ✕ Écarter l'alerte
                </Button>
              </div>

              <div className="mb-4">
                <TextArea
                  label="Note (optionnelle)"
                  placeholder="Contexte, justification…"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={3}
                  disabled={submitState.kind === 'submitting'}
                />
              </div>

              {submitState.kind === 'error' && (
                <p className="mb-3 text-sm text-red-600">{submitState.message}</p>
              )}

              <Button
                onClick={handleSubmit}
                disabled={!action || submitState.kind === 'submitting'}
                className="w-full"
              >
                {submitState.kind === 'submitting' ? 'Validation…' : 'Valider la décision'}
              </Button>
            </>
          )}
        </>
      )}
    </Drawer>
  );
}

function ConflictNotice({
  reviewedBy,
  reviewedAt,
  onBack,
}: {
  reviewedBy: string | null;
  reviewedAt: string | null;
  onBack: () => void;
}) {
  // Dégrade honnêtement si le lookup post-409 n'a pas retrouvé l'alerte
  // (voir POINT OUVERT en tête de fichier) plutôt que d'inventer un nom.
  const detail =
    reviewedBy && reviewedAt
      ? `Cette alerte a été traitée par ${reviewedBy}, ${formatRelativeTime(reviewedAt)}.`
      : 'Cette alerte a été traitée par un autre agent entre-temps.';

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="font-semibold text-amber-900">⚠ Alerte déjà traitée</p>
      <p className="mt-1 text-sm text-amber-800">
        {detail} Aucune action supplémentaire n'est nécessaire.
      </p>
      <Button className="mt-4 w-full" onClick={onBack}>
        Retour à la liste
      </Button>
    </div>
  );
}
