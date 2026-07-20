using FraudDetection.Domain.Enums;

namespace FraudDetection.Domain.ValueObjects;

/// <summary>
/// Encapsule le résultat complet retourné par FastAPI (ScoreOut).
/// IMMUTABLE — reflète une décision déjà prise côté Python, ne la recalcule JAMAIS.
///
/// Les seuils APPROVE/REVIEW/BLOCK sont définis et appliqués exclusivement dans
/// FraudScore.compute() côté Python (THRESHOLD_BLOCK=0.70, THRESHOLD_REVIEW=0.40).
/// Toute logique de seuil côté .NET serait une duplication dangereuse susceptible
/// de diverger silencieusement du comportement Python réel.
/// </summary>
public sealed record RiskScore
{
    public int Score { get; }
    public DecisionStatus Decision { get; }
    public string? FraudType { get; }
    public string? AlertId { get; }

    // Sous-scores individuels des quatre modèles — optionnels (null si modèle non disponible)
    public double? XgboostScore { get; }
    public double? IsolationScore { get; }
    public double? TftScore { get; }
    public double? GnnScore { get; }

    public double? InferenceTimeMs { get; }
    public string? ModelVersion { get; }

    public RiskScore(
        int score,
        DecisionStatus decision,
        string? fraudType = null,
        string? alertId = null,
        double? xgboostScore = null,
        double? isolationScore = null,
        double? tftScore = null,
        double? gnnScore = null,
        double? inferenceTimeMs = null,
        string? modelVersion = null)
    {
        if (score < 0 || score > 100)
            throw new ArgumentOutOfRangeException(
                nameof(score),
                $"Le score doit être entre 0 et 100. Valeur reçue : {score}");

        // AlertId ne doit être présent que pour REVIEW ou BLOCK — cohérent avec Python
        if (alertId is not null && decision == DecisionStatus.Approve)
            throw new ArgumentException(
                "Un AlertId ne peut pas être associé à une décision APPROVE.",
                nameof(alertId));

        Score = score;
        Decision = decision;
        FraudType = fraudType;
        AlertId = alertId;
        XgboostScore = xgboostScore;
        IsolationScore = isolationScore;
        TftScore = tftScore;
        GnnScore = gnnScore;
        InferenceTimeMs = inferenceTimeMs;
        ModelVersion = modelVersion;
    }

    /// <summary>
    /// Score de résilience par défaut quand fraud-ml-service est indisponible.
    /// REVIEW — jamais APPROVE (fail-safe cohérent avec la philosophie de risque du système :
    /// manquer une fraude coûte plus cher qu'une fausse alerte).
    /// Polly circuit breaker déclenche ce fallback via MlScoringService.
    /// </summary>
    public static RiskScore DefaultReview() =>
        new(score: 50, decision: DecisionStatus.Review, fraudType: "UNAVAILABLE");

    public bool RequiresHumanReview =>
        Decision == DecisionStatus.Review || Decision == DecisionStatus.Block;

    public override string ToString() =>
        $"[{Decision}] Score={Score} FraudType={FraudType ?? "N/A"}";
}