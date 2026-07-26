/**
 * Types reflétant EXACTEMENT le contrat de fraud-backend (.NET), tel que
 * documenté dans FRONTEND_STARTER_PACK.md (178 tests backend, 0 échec).
 * Ne jamais modifier ces types sans revérifier contre le vrai contrat —
 * voir react-frontend-builder, principe #3.
 */

// -----------------------------------------------------------------------
// Décision — ATTENTION : deux casses différentes coexistent réellement
// dans le backend, ce n'est pas une erreur à "corriger" côté frontend.
//
//   GET /alerts                -> "Approve" | "Review" | "Block"   (Pascal)
//   POST /webhook, GET /reports -> "APPROVE" | "REVIEW" | "BLOCK"  (majuscules)
//
// DecisionRaw représente la valeur BRUTE telle qu'elle arrive de l'API,
// sans normalisation. La normalisation d'affichage se fait exclusivement
// dans utils/decisionCasing.ts — jamais ici, jamais par un composant.
// -----------------------------------------------------------------------
export type DecisionPascal = 'Approve' | 'Review' | 'Block';
export type DecisionUpper = 'APPROVE' | 'REVIEW' | 'BLOCK';
export type DecisionRaw = DecisionPascal | DecisionUpper;

// -----------------------------------------------------------------------
// Statut d'une alerte — AlertStatus côté backend (Domain/Enums/AlertStatus.cs)
// Toujours en Pascal, contrairement à decision, aucune incohérence connue
// à ce jour sur cet enum.
// -----------------------------------------------------------------------
export type AlertStatus = 'Pending' | 'Confirmed' | 'Dismissed';

// -----------------------------------------------------------------------
// FraudType — liste NON exhaustive ici volontairement.
// La documentation technique liste : SIM_SWAPPING, OTP_THEFT, USSD_SCAM,
// FAKE_MERCHANT, FRAUDULENT_AGENT, STRUCTURING, LAYERING, MULE_ACCOUNT,
// UNUSUAL_BEHAVIOR, UNKNOWN — mais rien ne garantit que cette liste est
// figée côté backend (aucun enum fermé exposé dans le pack de contrats
// frontend). On type donc en string plutôt qu'en union fermée, pour ne
// jamais planter sur une valeur légitime non prévue ici.
// Le mapping FraudType -> libellé FR affichable vit dans utils/fraudTypeLabels.ts,
// PAS ici (même principe que decisionCasing.ts).
// -----------------------------------------------------------------------
export type FraudType = string;

export interface AlertListItem {
  alertId: string;
  transactionId: string;
  operator: string;
  decision: DecisionRaw;
  score: number;
  fraudType: FraudType;
  status: AlertStatus;
  createdAt: string; // ISO 8601 UTC
  reviewedAt: string | null;
  reviewedBy: string | null;
}

export interface AlertsResponse {
  alerts: AlertListItem[];
  totalPending: number;
  page: number;
  pageSize: number;
}

export interface GetAlertsParams {
  status?: AlertStatus;
  page?: number;
  pageSize?: number;
}

// -----------------------------------------------------------------------
// POST /alerts/{alertId}/validate
// action DOIT être envoyé exactement "Confirm" ou "Dismiss" — ce ne sont
// pas des libellés d'affichage, ce sont les valeurs contractuelles.
// Ne jamais dériver cette valeur d'un texte de bouton affiché (ex: ne pas
// envoyer "Confirmer la fraude", même si c'est le libellé du bouton UI).
// -----------------------------------------------------------------------
export type AlertValidationAction = 'Confirm' | 'Dismiss';

export interface ValidateAlertRequest {
  action: AlertValidationAction;
  note?: string;
}

export interface ValidateAlertResponse {
  alertId: string;
  action: AlertValidationAction;
  strReportTriggered: boolean;
}

// -----------------------------------------------------------------------
// Erreurs — forme unique retournée par GlobalExceptionMiddleware pour
// TOUTE erreur, y compris les cas métier typés (404/409) et le générique
// 500. `details` est une liste de chaînes non structurées : le backend ne
// renvoie PAS qui a traité l'alerte ni quand dans le corps de l'erreur.
// Toute info affichée au-delà de `error`/`details` (ex: "confirmée par
// Aïcha M.") doit venir d'un second appel à GET /alerts après le 409,
// jamais être supposée présente dans la réponse d'erreur elle-même.
// -----------------------------------------------------------------------
export type ApiErrorCode =
  | 'alert_not_found' // 404
  | 'alert_already_processed' // 409
  | 'internal_server_error'; // 500 (et tout code non mappé explicitement)

export interface ApiErrorResponse {
  error: ApiErrorCode;
  details: string[] | null;
}