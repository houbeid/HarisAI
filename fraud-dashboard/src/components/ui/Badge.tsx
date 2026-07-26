import type { ReactNode } from 'react';
import { TONE_CLASSES, type Tone } from './toneStyles';

interface BadgeProps {
  tone: Tone;
  children: ReactNode;
}

/**
 * Primitif générique — ne connaît ni Decision ni AlertStatus. Les
 * composants métier (AlertList, AlertDetailPanel...) sont responsables de
 * traduire une donnée réelle en `tone` avant d'appeler ce composant :
 *   <Badge tone={decisionTone(alert.decision)}>{decisionLabel(alert.decision)}</Badge>
 * Jamais l'inverse — Badge ne doit jamais importer utils/decisionCasing.
 */
export function Badge({ tone, children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
