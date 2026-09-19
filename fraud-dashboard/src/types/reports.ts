import type { DecisionUpper, FraudType } from './alerts';

/**
 * Types reflétant EXACTEMENT le contrat GET /reports de fraud-backend.
 * Endpoint réservé aux rôles compliance_officer et supervisor — l'accès
 * est vérifié côté backend (JWT), mais la navigation frontend doit aussi
 * masquer l'entrée "Rapports STR" pour les autres rôles (voir capture
 * état vide : la sidebar d'un agent standard n'affiche pas cette section).
 */

// -----------------------------------------------------------------------
// decision — ICI, contrairement à AlertListItem, TOUJOURS en majuscules.
// Le pack le confirme explicitement : StrReportData normalise via
// .ToUpperInvariant() à la construction, côté backend. Ne pas réutiliser
// DecisionRaw ici : ce serait rouvrir une ambiguïté qui n'existe pas sur
// cet endpoint précis. C'est un des deux seuls endroits du code (avec
// POST /webhook, jamais consommé par le frontend) où la casse est fixe.
// -----------------------------------------------------------------------
export interface StrReportItem {
  reportId: string;
  alertId: string;
  transactionId: string;
  operatorCode: string;
  fraudType: FraudType;
  riskScore: number;
  decision: DecisionUpper;
  // POINT OUVERT (hérité du backend, voir mémoire projet) : confirmedBy
  // est une chaîne brute — l'exemple du pack montre un email
  // ("agent@bankily.mr"), PAS un nom lisible. Aucun endpoint d'annuaire
  // agents n'existe à ce jour pour résoudre cette chaîne en nom affichable.
  // Ne jamais supposer un format ("Prénom Nom.") côté composant : afficher
  // la valeur telle quelle jusqu'à ce qu'un endpoint de résolution existe.
  confirmedBy: string;
  agentNote: string | null;
  generatedAt: string; // ISO 8601 UTC
}

export interface ReportsResponse {
  reports: StrReportItem[];
  page: number;
  pageSize: number;
  // Comble le point ouvert 5 (Session 2) : total réel indépendant de la
  // pagination — remplace l'heuristique "Suivant désactivé si la page est
  // incomplète" de la Session 1 par une vraie pagination.
  totalCount: number;
}

export interface GetReportsParams {
  page?: number;
  pageSize?: number;
}