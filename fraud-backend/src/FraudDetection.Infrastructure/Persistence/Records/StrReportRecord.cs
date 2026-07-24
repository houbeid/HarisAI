namespace FraudDetection.Infrastructure.Persistence.Records;

/// <summary>
/// Modèle de persistance EF Core pour un rapport STR (Suspicious Transaction
/// Report) généré suite à la confirmation d'une fraude par un agent de
/// conformité (Alert.Confirm() → GenerateStrReportCommand).
///
/// PÉRIMÈTRE : stocke le rapport localement, prêt à être transmis à la BCM
/// dès que le canal de transmission sera défini (voir IBcmReportingService,
/// commenté dans GenerateStrReportHandler — point ouvert non résolu).
/// En attendant, ce Record permet au moins aux agents de conformité de
/// consulter l'historique des rapports générés via ReportController.
/// </summary>
public sealed class StrReportRecord
{
    /// <summary>Clé primaire — format lisible STR-{OPERATOR}-{TIMESTAMP}-{HASH}.</summary>
    public required string ReportId { get; set; }

    public required string AlertId { get; set; }
    public required string TransactionId { get; set; }
    public required string Operator { get; set; }
    public required string FraudType { get; set; }
    public required int RiskScore { get; set; }
    public required string Decision { get; set; }
    public required string ConfirmedBy { get; set; }
    public string? AgentNote { get; set; }
    public required DateTime GeneratedAt { get; set; }

    // Sous-scores ML — dénormalisés, mêmes principes que TransactionRecord/AlertRecord
    public double? XgboostScore { get; set; }
    public double? IsolationScore { get; set; }
    public double? TftScore { get; set; }
    public double? GnnScore { get; set; }

    /// <summary>
    /// Vrai une fois le rapport effectivement transmis à la BCM.
    /// Toujours false tant que IBcmReportingService n'est pas implémenté —
    /// pas un mensonge, juste un état honnête reflétant la réalité actuelle.
    /// </summary>
    public required bool Transmitted { get; set; }

    public DateTime? TransmittedAt { get; set; }
}