import type { AlertStatus } from '../types/alerts';

/**
 * Contrairement à fraudTypeLabels.ts, AlertStatus est un enum FERMÉ
 * (Domain/Enums/AlertStatus.cs, 3 valeurs, pas de fondement pour une 4e).
 * Record<AlertStatus, string> sans Partial : TypeScript nous force à
 * couvrir les 3 cas, un repli serait ici un signe d'erreur silencieuse
 * plutôt qu'une protection légitime.
 */
const ALERT_STATUS_LABELS: Record<AlertStatus, string> = {
  Pending: 'En attente',
  Confirmed: 'Confirmée',
  Dismissed: 'Écartée',
};

export function alertStatusLabel(status: AlertStatus): string {
  return ALERT_STATUS_LABELS[status];
}

/**
 * Catégorie de ton, même principe que decisionCasing.ts — le composant
 * Badge choisit la vraie couleur. 'neutral' pour En attente (pas encore
 * de verdict), 'info' pour Confirmée, 'muted' pour Écartée : cohérent
 * avec la maquette (gris / bleu / lavande).
 */
export type StatusTone = 'neutral' | 'info' | 'muted';

const ALERT_STATUS_TONES: Record<AlertStatus, StatusTone> = {
  Pending: 'neutral',
  Confirmed: 'info',
  Dismissed: 'muted',
};

export function alertStatusTone(status: AlertStatus): StatusTone {
  return ALERT_STATUS_TONES[status];
}