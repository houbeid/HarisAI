using FraudDetection.Domain.Entities;
using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Port vers fraud-ml-service (FastAPI Python).
/// L'Application définit CE QU'ELLE VEUT — pas comment l'obtenir.
/// L'implémentation concrète (MlScoringService.cs, Infrastructure) gère :
///   - La sérialisation Transaction → TransactionIn (DTO FastAPI)
///   - L'appel HTTP POST /analyze avec le header X-Api-Key
///   - Le retry et circuit breaker Polly
///   - La désérialisation ScoreOut → RiskScore
///   - Le fallback RiskScore.DefaultReview() si FastAPI est indisponible
///
/// Cette interface ne mentionne jamais HTTP, Polly, TransactionIn, ScoreOut,
/// ni aucun détail d'infrastructure — c'est intentionnel.
/// </summary>
public interface IMlScoringService
{
    /// <summary>
    /// Analyse synchrone d'une transaction — correspond à POST /analyze côté FastAPI.
    /// Retourne toujours un RiskScore, même si FastAPI est indisponible :
    /// dans ce cas, MlScoringService retourne RiskScore.DefaultReview() via Polly fallback.
    /// Ne lève jamais d'exception sur une panne FastAPI — la résilience est encapsulée
    /// dans l'implémentation Infrastructure, pas dans les handlers Application.
    /// </summary>
    Task<RiskScore> AnalyzeAsync(
        Transaction transaction,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Vérifie que fraud-ml-service est opérationnel — correspond à GET /health.
    /// Utilisé par :
    ///   - HealthController (/health/ready) pour K8s readiness probe
    ///   - PendingTransactionWorker pour décider de relancer la queue locale
    /// Retourne false si FastAPI ne répond pas dans le délai imparti,
    /// sans lever d'exception.
    /// </summary>
    Task<bool> IsHealthyAsync(CancellationToken cancellationToken = default);
}