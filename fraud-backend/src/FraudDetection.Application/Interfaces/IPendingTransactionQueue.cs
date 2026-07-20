using FraudDetection.Domain.Entities;

namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Port de la file de résilience locale.
/// Quand fraud-ml-service (FastAPI) est indisponible, les transactions
/// reçoivent une décision par défaut REVIEW (RiskScore.DefaultReview())
/// et sont placées dans cette file pour être rescorées dès que FastAPI revient.
///
/// IMPLÉMENTATION : PendingTransactionRepository.cs (Infrastructure) utilise
/// PostgreSQL avec SELECT ... FOR UPDATE SKIP LOCKED — pattern natif pour
/// consommation concurrente sûre sans double traitement, même avec
/// plusieurs pods .NET actifs simultanément.
///
/// CONSOMMATEUR EXCLUSIF : PendingTransactionWorker (BackgroundService, replicas:1)
/// qui vérifie IMlScoringService.IsHealthyAsync() avant chaque dépilage.
///
/// CE QUE CETTE FILE N'EST PAS :
/// - La file Redis côté Python (/analyze-async) — celle-là est pour les pics de charge
/// - Le tracking des notifications opérateur échouées — c'est ITransactionRepository
/// Cette file couvre uniquement le cas "FastAPI était down au moment de la réception".
/// </summary>
public interface IPendingTransactionQueue
{
    /// <summary>
    /// Ajoute une transaction à la file de rescoring.
    /// Appelé dans AnalyzeTransactionHandler quand Polly détecte que FastAPI
    /// est indisponible et retourne RiskScore.DefaultReview().
    /// Idempotent — si la transaction est déjà dans la file, ne l'ajoute pas en double.
    /// </summary>
    Task EnqueueAsync(
        Transaction transaction,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Dépile un lot de transactions à rescorer.
    /// Utilise SELECT ... FOR UPDATE SKIP LOCKED — garantit qu'avec N pods .NET,
    /// chaque transaction n'est traitée que par un seul pod à la fois.
    /// Appelé exclusivement par PendingTransactionWorker.
    /// </summary>
    Task<IReadOnlyList<Transaction>> DequeueAsync(
        int batchSize = 10,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Confirme qu'une transaction a été rescorée avec succès.
    /// La retire définitivement de la file.
    /// Appelé par PendingTransactionWorker après réception d'un RiskScore réel
    /// (pas un DefaultReview) depuis FastAPI.
    /// </summary>
    Task AcknowledgeAsync(
        string transactionId,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Remet une transaction en file après un échec de rescoring.
    /// Incrémente le compteur de tentatives — une transaction qui dépasse
    /// le seuil maxAttempts est sortie de la file et loggée en erreur
    /// pour intervention manuelle.
    /// </summary>
    Task RequeueAsync(
        string transactionId,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Nombre de transactions en attente de rescoring par opérateur.
    /// Exposé via MetricsCollector comme jauge Prometheus —
    /// un pic anormal indique une panne FastAPI prolongée.
    /// </summary>
    Task<int> GetQueueSizeAsync(
        string operatorCode,
        CancellationToken cancellationToken = default);
}