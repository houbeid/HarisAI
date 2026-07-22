namespace FraudDetection.Infrastructure.Persistence.Records;

/// <summary>
/// Modèle de persistance EF Core pour une transaction traitée côté .NET.
/// Plat, mutable, sans validation — c'est le rôle du Domain (Transaction.cs),
/// pas de ce Record. TransactionRepository fait le mapping dans les deux sens.
///
/// PÉRIMÈTRE : représente l'état complet du traitement .NET d'une transaction —
/// le webhook reçu, le score ML reçu, et le statut de notification retour
/// vers l'opérateur. Distinct de l'audit trail immuable ml_audit (Python).
///
/// Les sous-scores ML (Xgboost, Isolation, Tft, Gnn) sont dénormalisés en
/// colonnes séparées plutôt qu'en JSON — permet des requêtes analytiques
/// simples (ex: moyenne du score XGBoost sur une période) sans parsing JSON.
/// </summary>
public sealed class TransactionRecord
{
    /// <summary>Clé primaire — identique à Transaction.TransactionId du Domain.</summary>
    public required string TransactionId { get; set; }

    public required string ClientToken { get; set; }
    public required decimal Amount { get; set; }
    public required string Currency { get; set; }
    public required string Channel { get; set; }
    public required string Zone { get; set; }
    public required string Operator { get; set; }
    public required string DeviceId { get; set; }
    public required bool SimChanged72h { get; set; }
    public DateTime? SimChangedAt { get; set; }
    public required string BeneficiaryToken { get; set; }
    public required bool BeneficiaryIsMerchant { get; set; }
    public string? AgentId { get; set; }
    public required bool UssdSession { get; set; }
    public required DateTime Timestamp { get; set; }

    // ── Résultat ML — renseigné après appel à fraud-ml-service ────────────────

    /// <summary>Null tant que UpdateScoreAsync n'a pas été appelé.</summary>
    public int? Score { get; set; }

    /// <summary>"APPROVE" | "REVIEW" | "BLOCK" — null tant que non scoré.</summary>
    public string? Decision { get; set; }

    public string? FraudType { get; set; }
    public string? AlertId { get; set; }
    public double? XgboostScore { get; set; }
    public double? IsolationScore { get; set; }
    public double? TftScore { get; set; }
    public double? GnnScore { get; set; }
    public double? InferenceTimeMs { get; set; }
    public string? ModelVersion { get; set; }

    /// <summary>
    /// Vrai si le score provient d'un fallback Polly (RiskScore.DefaultReview())
    /// plutôt que d'une vraie réponse FastAPI. Permet de distinguer un REVIEW
    /// "voulu" par XGBoost d'un REVIEW "par défaut" faute de réponse ML.
    /// </summary>
    public bool IsDefaultReview { get; set; }

    // ── Notification opérateur ──────────────────────────────────────────────

    /// <summary>"Pending" | "Sent" | "Failed" — miroir de NotificationStatus (Application).</summary>
    public required string NotificationStatus { get; set; }

    // ── Métadonnées de traçabilité ──────────────────────────────────────────

    public required DateTime ReceivedAt { get; set; }
    public DateTime? ScoredAt { get; set; }
}