namespace FraudDetection.Infrastructure.Persistence.Records;

/// <summary>
/// Modèle de persistance EF Core pour une alerte.
/// Plat, mutable — AlertRepository fait le mapping vers/depuis Alert (Domain).
///
/// Le score complet (RiskScore) est dénormalisé en colonnes séparées,
/// comme dans TransactionRecord, pour permettre des requêtes directes
/// (ex: alertes triées par score décroissant) sans parsing.
/// </summary>
public sealed class AlertRecord
{
    /// <summary>Clé primaire locale .NET — Alert.Id (Guid) du Domain.</summary>
    public required Guid Id { get; set; }

    /// <summary>Identifiant FastAPI — format ALT-XXXXXXXXXXXXXXXX. Indexé unique.</summary>
    public required string AlertId { get; set; }

    /// <summary>Indexé — utilisé par GetByTransactionIdAsync pour l'idempotence.</summary>
    public required string TransactionId { get; set; }

    public required string Operator { get; set; }

    // ── Score dénormalisé ────────────────────────────────────────────────────
    public required int Score { get; set; }
    public required string Decision { get; set; }
    public string? FraudType { get; set; }
    public double? XgboostScore { get; set; }
    public double? IsolationScore { get; set; }
    public double? TftScore { get; set; }
    public double? GnnScore { get; set; }

    // ── Cycle de vie ──────────────────────────────────────────────────────────

    /// <summary>"Pending" | "Confirmed" | "Dismissed" — miroir de AlertStatus (Domain).</summary>
    public required string Status { get; set; }

    public required DateTime CreatedAt { get; set; }
    public DateTime? ReviewedAt { get; set; }
    public string? ReviewedBy { get; set; }
    public string? ReviewNote { get; set; }
}