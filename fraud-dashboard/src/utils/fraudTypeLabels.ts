import type { FraudType } from '../types/alerts';

/**
 * Traductions connues, d'après la documentation technique du moteur ML
 * (enums.py). Ce n'est PAS une liste fermée — types/alerts.ts type déjà
 * FraudType en `string` ouvert pour cette raison précise. La preuve
 * concrète : la maquette a produit "Prise de contrôle", une valeur qui ne
 * correspond à aucune entrée documentée ci-dessous — probablement un type
 * ajouté côté ML depuis la rédaction de la doc technique. Le repli
 * humanizeFallback() gère exactement ce cas, sans planter ni afficher vide.
 */
const KNOWN_LABELS_FR: Partial<Record<string, string>> = {
  SIM_SWAPPING: 'SIM swapping',
  OTP_THEFT: 'Vol de code OTP',
  USSD_SCAM: 'Arnaque USSD',
  FAKE_MERCHANT: 'Faux marchand',
  FRAUDULENT_AGENT: 'Agent frauduleux',
  STRUCTURING: 'Structuring',
  LAYERING: 'Layering',
  MULE_ACCOUNT: 'Compte mule',
  UNUSUAL_BEHAVIOR: 'Comportement inhabituel',
  UNKNOWN: 'Type inconnu',
};

/**
 * Repli pour toute valeur non listée ci-dessus : "ACCOUNT_TAKEOVER"
 * devient "Account takeover" plutôt que de rester en majuscules brutes
 * ou de casser l'affichage. Pas une vraie traduction FR — un filet de
 * sécurité lisible, à préférer à un badge vide ou à un crash.
 */
function humanizeFallback(raw: string): string {
  const spaced = raw.toLowerCase().replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function fraudTypeLabel(raw: FraudType): string {
  return KNOWN_LABELS_FR[raw] ?? humanizeFallback(raw);
}