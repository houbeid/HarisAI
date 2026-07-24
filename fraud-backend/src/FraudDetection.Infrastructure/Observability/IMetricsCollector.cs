namespace FraudDetection.Infrastructure.Observability;

/// <summary>
/// Port de collecte de métriques Prometheus côté .NET.
/// Distinct des 13 métriques déjà exposées côté Python (infrastructure/monitoring/metrics.py)
/// — les noms ne doivent jamais entrer en collision (voir note d'architecture :
/// "ne pas redéfinir transactions_total différemment des deux côtés").
///
/// PÉRIMÈTRE VOLONTAIREMENT MINIMAL : cette interface ne couvre que les
/// métriques ayant un consommateur réel déjà identifié dans le code écrit
/// à ce jour. Pas de méthode spéculative pour un futur besoin — cohérent
/// avec le choix déjà fait pour RedisService (pas de cache générique
/// anticipé sans cas d'usage concret).
///
/// Étendue plus tard, au moment où TransactionController existera,
/// avec des méthodes pour les webhooks reçus / rejetés par l'authentification.
/// </summary>
public interface IMetricsCollector
{
    /// <summary>
    /// Enregistre le résultat d'un appel à fraud-ml-service — appelé depuis
    /// MlScoringService.AnalyzeAsync() à chaque tentative, succès ou fallback.
    /// isDefaultReview = true signale un RiskScore.DefaultReview() (Polly fallback),
    /// pas une vraie réponse FastAPI — distinction essentielle pour détecter
    /// une dégradation du service ML avant qu'elle ne devienne critique.
    /// </summary>
    void RecordMlCall(bool isDefaultReview, double durationMs);

    /// <summary>
    /// Met à jour la jauge de taille de la file de résilience pour un opérateur.
    /// Appelé périodiquement par PendingMetricsPoller (BackgroundService),
    /// pas depuis PendingTransactionRepository lui-même — garde le repository
    /// inchangé, cohérent avec le modèle "pull" déjà utilisé par Prometheus.
    /// Un pic anormal et persistant indique une panne FastAPI prolongée.
    /// </summary>
    void SetPendingQueueSize(string operatorCode, int size);

    /// <summary>
    /// Met à jour la jauge du nombre d'alertes Pending pour un opérateur.
    /// Appelé périodiquement par PendingMetricsPoller, pas depuis
    /// AlertRepository — même principe que SetPendingQueueSize.
    /// Un nombre élevé et croissant indique un backlog de traitement
    /// par les agents de conformité.
    /// </summary>
    void SetAlertsPendingCount(string operatorCode, int count);
}