import type { DecisionRaw } from '../types/alerts';

/**
 * SEUL fichier du code qui connaît l'incohérence de casse documentée dans
 * FRONTEND_STARTER_PACK.md : GET /alerts renvoie "Review", GET /reports
 * renvoie "REVIEW". Aucun composant ne doit faire .toUpperCase() ou
 * comparer une decision brute lui-même — tout passe par ici.
 *
 * `Severity` est la forme canonique interne (minuscules), utilisée pour la
 * LOGIQUE (comparaisons, couleurs). L'AFFICHAGE utilise toujours le même
 * libellé Pascal ("Approve"/"Review"/"Block"), indépendamment de la casse
 * brute reçue — ce choix normalise volontairement l'UI plutôt que de
 * refléter fidèlement chaque endpoint (contrairement aux types, où la
 * casse brute réelle est préservée sans altération).
 */
export type Severity = 'approve' | 'review' | 'block';

export function normalizeDecision(raw: DecisionRaw): Severity {
  switch (raw) {
    case 'Approve':
    case 'APPROVE':
      return 'approve';
    case 'Review':
    case 'REVIEW':
      return 'review';
    case 'Block':
    case 'BLOCK':
      return 'block';
    default: {
      // Garde défensive : si le backend introduit une 4e valeur un jour,
      // on ne veut pas planter silencieusement en production — un signal
      // clair en dev vaut mieux qu'un badge vide.
      const exhaustiveCheck: never = raw;
      console.error(`Decision inconnue reçue du backend : ${exhaustiveCheck}`);
      return 'review'; // repli le plus prudent : force une revue humaine
    }
  }
}

const DECISION_LABELS: Record<Severity, string> = {
  approve: 'Approve',
  review: 'Review',
  block: 'Block',
};

export function decisionLabel(raw: DecisionRaw): string {
  return DECISION_LABELS[normalizeDecision(raw)];
}

/**
 * Catégorie sémantique de couleur, pas une couleur elle-même — le
 * composant Badge (couche UI primitifs) décide des vraies valeurs CSS.
 * Convention validée avec la maquette : Block=rouge, Review=ambre,
 * Approve=vert.
 */
export type SeverityTone = 'danger' | 'warning' | 'success';

const SEVERITY_TONES: Record<Severity, SeverityTone> = {
  block: 'danger',
  review: 'warning',
  approve: 'success',
};

export function decisionTone(raw: DecisionRaw): SeverityTone {
  return SEVERITY_TONES[normalizeDecision(raw)];
}