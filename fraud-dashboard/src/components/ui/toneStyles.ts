/**
 * Union des deux familles de ton utilisées dans l'app (sévérité de
 * décision + statut de traitement d'alerte) — voir utils/decisionCasing.ts
 * et utils/alertStatusLabels.ts. Ce fichier ne connaît AUCUNE donnée
 * métier (pas de Decision, pas de AlertStatus) : il traduit un ton
 * abstrait en classes Tailwind, point. Le lien ton métier -> tone
 * générique se fait dans les composants métier (couche au-dessus),
 * jamais ici — cohérent avec "UI primitifs sans dépendance métier".
 */
export type Tone = 'danger' | 'warning' | 'success' | 'neutral' | 'info' | 'muted';

export const TONE_CLASSES: Record<Tone, string> = {
  danger: 'bg-severity-danger-bg border-severity-danger-border text-severity-danger-text',
  warning: 'bg-severity-warning-bg border-severity-warning-border text-severity-warning-text',
  success: 'bg-severity-success-bg border-severity-success-border text-severity-success-text',
  neutral: 'bg-status-neutral-bg border-transparent text-status-neutral-text',
  info: 'bg-status-info-bg border-transparent text-status-info-text',
  muted: 'bg-status-muted-bg border-transparent text-status-muted-text',
};