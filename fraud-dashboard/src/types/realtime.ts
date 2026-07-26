import type { DecisionRaw, FraudType } from './alerts';

/**
 * Type du payload reçu via SignalR sur /alertHub, événement "ReceiveAlert".
 * Reflète exactement l'exemple du pack — PAS le même objet que AlertListItem :
 * un sous-ensemble volontairement plus restreint (pas de status, createdAt,
 * reviewedAt/reviewedBy — l'alerte vient d'être créée, ces champs n'ont pas
 * encore de sens ou ne sont pas transmis par le Hub).
 *
 * decision est ici typé DecisionRaw (pas DecisionPascal) par prudence :
 * le pack montre "Review" dans l'exemple SignalR, cohérent avec la casse
 * de GET /alerts, mais rien ne garantit contractuellement que le Hub et
 * GET /alerts partagent exactement la même sérialisation dans le temps —
 * les deux viennent de sources différentes côté backend (AlertHub vs
 * AlertController). Élargir ici coûte peu ; se tromper par excès de
 * confiance casserait silencieusement un composant de production.
 */
export interface ReceiveAlertPayload {
  alertId: string;
  transactionId: string;
  decision: DecisionRaw;
  score: number;
  fraudType: FraudType;
}

// -----------------------------------------------------------------------
// POINT OUVERT (voir FRONTEND_STARTER_PACK.md) : aucune alerte créée par
// le Worker en arrière-plan (NoOpAlertNotifier) n'émet cet événement.
// Toute UI construite sur ReceiveAlertPayload doit donc être doublée d'un
// rafraîchissement périodique via GET /alerts (TanStack Query,
// refetchInterval) — jamais considérer ce flux comme la source complète
// des alertes en attente. Voir capture "reçu hors temps réel" côté maquette.
// -----------------------------------------------------------------------