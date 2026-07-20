using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Domain.Events;

/// <summary>
/// Événement émis quand une transaction a été analysée par fraud-ml-service,
/// quelle que soit la décision (APPROVE, REVIEW, BLOCK).
/// Utilisé pour déclencher la persistance locale et le monitoring.
/// </summary>
public sealed record TransactionAnalyzed
{
    public string TransactionId { get; }
    public string Operator { get; }
    public RiskScore Score { get; }
    public DateTime OccurredAt { get; }

    public TransactionAnalyzed(string transactionId, string @operator, RiskScore score)
    {
        if (string.IsNullOrWhiteSpace(transactionId))
            throw new ArgumentException("TransactionId ne peut pas être vide.", nameof(transactionId));

        if (string.IsNullOrWhiteSpace(@operator))
            throw new ArgumentException("Operator ne peut pas être vide.", nameof(@operator));

        TransactionId = transactionId.Trim();
        Operator = @operator.Trim().ToUpperInvariant();
        Score = score;
        OccurredAt = DateTime.UtcNow;
    }
}