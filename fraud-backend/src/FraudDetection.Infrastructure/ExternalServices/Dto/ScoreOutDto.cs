using System.Text.Json.Serialization;

namespace FraudDetection.Infrastructure.ExternalServices.Dto;

/// <summary>
/// Miroir EXACT d'un élément de la liste "reasons" dans ScoreOut (Python).
/// Représente un facteur explicatif SHAP pour la décision — utilisé
/// par fraud-dashboard pour afficher à l'agent de conformité pourquoi
/// une transaction a été signalée, en français et en arabe.
/// </summary>
public sealed class ShapReasonDto
{
    [JsonPropertyName("feature_name")]
    public required string FeatureName { get; init; }

    [JsonPropertyName("contribution")]
    public required double Contribution { get; init; }

    [JsonPropertyName("feature_value")]
    public required double FeatureValue { get; init; }

    [JsonPropertyName("readable_fr")]
    public required string ReadableFr { get; init; }

    [JsonPropertyName("readable_ar")]
    public required string ReadableAr { get; init; }
}

/// <summary>
/// Miroir EXACT du schéma Pydantic ScoreOut (presentation/schemas.py côté Python).
/// CONTRAT FIGÉ — ne jamais modifier sans coordination avec fraud-ml-service.
///
/// RÔLE : ce DTO n'existe que pour la désérialisation JSON depuis POST /analyze.
/// Il n'est jamais exposé en dehors de MlScoringService — le mapping
/// ScoreOutDto → RiskScore (domaine) se fait exclusivement dans
/// MlScoringService.AnalyzeAsync().
///
/// RÈGLE DE MAPPING IMPORTANTE :
///   decision (string "APPROVE"/"REVIEW"/"BLOCK") → DecisionStatus (enum .NET)
///   Ce mapping ne réinterprète JAMAIS le score pour recalculer la décision —
///   il se contente de traduire la string Python vers l'enum .NET.
///   Toute décision non reconnue doit lever une exception explicite,
///   jamais un fallback silencieux vers une valeur par défaut.
/// </summary>
public sealed class ScoreOutDto
{
    [JsonPropertyName("transaction_id")]
    public required string TransactionId { get; init; }

    /// <summary>Score entier 0-100.</summary>
    [JsonPropertyName("score")]
    public required int Score { get; init; }

    /// <summary>"APPROVE" | "REVIEW" | "BLOCK" — mappé vers DecisionStatus enum.</summary>
    [JsonPropertyName("decision")]
    public required string Decision { get; init; }

    /// <summary>Ex: "SIM_SWAPPING", "STRUCTURING", "UNKNOWN". Null possible.</summary>
    [JsonPropertyName("fraud_type")]
    public string? FraudType { get; init; }

    /// <summary>Présent uniquement si REVIEW ou BLOCK — format ALT-XXXXXXXXXXXXXXXX.</summary>
    [JsonPropertyName("alert_id")]
    public string? AlertId { get; init; }

    [JsonPropertyName("xgboost_score")]
    public double? XgboostScore { get; init; }

    [JsonPropertyName("isolation_score")]
    public double? IsolationScore { get; init; }

    [JsonPropertyName("tft_score")]
    public double? TftScore { get; init; }

    [JsonPropertyName("gnn_score")]
    public double? GnnScore { get; init; }

    [JsonPropertyName("reasons")]
    public List<ShapReasonDto>? Reasons { get; init; }

    [JsonPropertyName("inference_time_ms")]
    public double? InferenceTimeMs { get; init; }

    [JsonPropertyName("model_version")]
    public string? ModelVersion { get; init; }
}