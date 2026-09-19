using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Domain.Entities;

/// <summary>
/// Alerte générée pour toute transaction avec décision REVIEW ou BLOCK.
/// Traitée par un agent de conformité humain via fraud-dashboard.
///
/// IMPORTANT : Alert.cs côté .NET est un miroir en LECTURE du résultat
/// déjà calculé par FastAPI. Elle ne duplique pas la logique métier Python
/// (pas de is_likely_mule(), pas de calcul de score ici).
/// Son seul état mutable est le statut de traitement par l'agent.
/// </summary>
public sealed class Alert
{
    public Guid Id { get; }
    public string AlertId { get; }      // ALT-XXXXXXXXXXXXXXXX — format FastAPI
    public string TransactionId { get; }
    public string Operator { get; }
    public RiskScore Score { get; }

    /// <summary>
    /// Montant de la transaction ayant déclenché cette alerte — copié depuis
    /// Transaction.Amount au moment de la création (voir CreateAlertHandler).
    /// Ajouté après coup (le montant n'existait pas dans les premières
    /// versions d'Alert) — réclamé par la session frontend, absent de la
    /// maquette du dashboard sans lui.
    /// </summary>
    public Money Amount { get; }

    public AlertStatus Status { get; private set; }
    public DateTime CreatedAt { get; }
    public DateTime? ReviewedAt { get; private set; }
    public string? ReviewedBy { get; private set; }
    public string? ReviewNote { get; private set; }

    public Alert(
        string alertId,
        string transactionId,
        string @operator,
        RiskScore score,
        Money amount,
        DateTime createdAt)
    {
        if (string.IsNullOrWhiteSpace(alertId))
            throw new ArgumentException("AlertId ne peut pas être vide.", nameof(alertId));

        if (string.IsNullOrWhiteSpace(transactionId))
            throw new ArgumentException("TransactionId ne peut pas être vide.", nameof(transactionId));

        if (string.IsNullOrWhiteSpace(@operator))
            throw new ArgumentException("Operator ne peut pas être vide.", nameof(@operator));

        // Une alerte ne peut être créée que pour REVIEW ou BLOCK
        if (!score.RequiresHumanReview)
            throw new ArgumentException(
                $"Une alerte ne peut être créée que pour une décision REVIEW ou BLOCK. " +
                $"Décision reçue : {score.Decision}",
                nameof(score));

        Id = Guid.NewGuid();
        AlertId = alertId.Trim();
        TransactionId = transactionId.Trim();
        Operator = @operator.Trim().ToUpperInvariant();
        Score = score;
        Amount = amount;
        Status = AlertStatus.Pending;
        CreatedAt = createdAt;
    }

    /// <summary>
    /// L'agent de conformité confirme qu'il s'agit d'une vraie fraude.
    /// Déclenche la génération d'un rapport STR vers la BCM (via GenerateStrReport command).
    /// </summary>
    public void Confirm(string reviewedBy, string? note = null)
    {
        EnsureCanBeReviewed();
        Status = AlertStatus.Confirmed;
        ReviewedAt = DateTime.UtcNow;
        ReviewedBy = reviewedBy?.Trim();
        ReviewNote = note?.Trim();
    }

    /// <summary>
    /// L'agent de conformité écarte l'alerte — faux positif.
    /// </summary>
    public void Dismiss(string reviewedBy, string? note = null)
    {
        EnsureCanBeReviewed();
        Status = AlertStatus.Dismissed;
        ReviewedAt = DateTime.UtcNow;
        ReviewedBy = reviewedBy?.Trim();
        ReviewNote = note?.Trim();
    }

    private void EnsureCanBeReviewed()
    {
        if (Status != AlertStatus.Pending)
            throw new InvalidOperationException(
                $"L'alerte {AlertId} ne peut plus être modifiée — statut actuel : {Status}.");
    }

    public bool IsPending => Status == AlertStatus.Pending;
    public bool RequiresStrReport => Status == AlertStatus.Confirmed;

    public override string ToString() =>
        $"[{AlertId}] {Score.Decision} — Status={Status} Operator={Operator}";
}