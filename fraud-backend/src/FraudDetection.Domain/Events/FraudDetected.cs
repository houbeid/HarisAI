using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Domain.Events;

/// <summary>
/// Événement émis uniquement quand la décision est REVIEW ou BLOCK.
/// Déclenche la création d'une alerte et la notification temps réel
/// vers fraud-dashboard via AlertHub (SignalR).
///
/// Distinct de TransactionAnalyzed : tous les événements analysés
/// ne génèrent pas une alerte — seulement les cas suspects.
/// </summary>
public sealed record FraudDetected
{
    public string TransactionId { get; }
    public string Operator { get; }
    public RiskScore Score { get; }
    public string? FraudType { get; }
    public DecisionStatus Decision { get; }
    public DateTime OccurredAt { get; }

    public FraudDetected(string transactionId, string @operator, RiskScore score)
    {
        if (string.IsNullOrWhiteSpace(transactionId))
            throw new ArgumentException("TransactionId ne peut pas être vide.", nameof(transactionId));

        if (string.IsNullOrWhiteSpace(@operator))
            throw new ArgumentException("Operator ne peut pas être vide.", nameof(@operator));

        // FraudDetected ne doit être émis que pour les décisions qui nécessitent une action humaine
        if (!score.RequiresHumanReview)
            throw new ArgumentException(
                $"FraudDetected ne peut être émis que pour REVIEW ou BLOCK. " +
                $"Décision reçue : {score.Decision}",
                nameof(score));

        TransactionId = transactionId.Trim();
        Operator = @operator.Trim().ToUpperInvariant();
        Score = score;
        FraudType = score.FraudType;
        Decision = score.Decision;
        OccurredAt = DateTime.UtcNow;
    }
}