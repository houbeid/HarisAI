using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.ValueObjects;
using MediatR;

namespace FraudDetection.Application.Commands.AnalyzeTransaction;

/// <summary>
/// Commande MediatR déclenchée par TransactionController dès réception
/// d'un webhook opérateur valide (signature HMAC vérifiée).
///
/// CONTIENT le payload brut — pas une Transaction déjà adaptée.
/// C'est le Handler qui utilise OperatorAdapterRegistry pour transformer
/// RawWebhookPayload → Transaction, ce qui garde le Controller fin :
/// il reçoit, valide la signature, crée la commande, envoie via MediatR.
/// Il ne connaît pas les adaptateurs.
///
/// RETOURNE AnalyzeTransactionResult qui contient la décision finale
/// à retourner à l'opérateur (APPROVE/REVIEW/BLOCK + alertId si présent).
/// </summary>
public sealed record AnalyzeTransactionCommand : IRequest<AnalyzeTransactionResult>
{
    /// <summary>
    /// Payload brut reçu depuis l'opérateur — format propriétaire inconnu.
    /// Le Handler délègue sa transformation à l'adaptateur correspondant.
    /// </summary>
    public RawWebhookPayload Payload { get; }

    /// <summary>
    /// Identifiant de corrélation généré par CorrelationIdMiddleware.
    /// Propagé en header vers FastAPI et inclus dans tous les logs Serilog
    /// pour tracer une transaction de bout en bout entre .NET et Python.
    /// </summary>
    public string CorrelationId { get; }

    public AnalyzeTransactionCommand(RawWebhookPayload payload, string correlationId)
    {
        ArgumentNullException.ThrowIfNull(payload);

        if (string.IsNullOrWhiteSpace(correlationId))
            throw new ArgumentException(
                "CorrelationId ne peut pas être vide.", nameof(correlationId));

        Payload = payload;
        CorrelationId = correlationId;
    }
}

/// <summary>
/// Résultat retourné par le Handler au Controller.
/// Le Controller le traduit en réponse HTTP vers l'opérateur.
/// </summary>
public sealed record AnalyzeTransactionResult
{
    public string TransactionId { get; }
    public RiskScore Score { get; }

    /// <summary>
    /// Vrai si FastAPI était indisponible et que la décision est un DefaultReview.
    /// Le Controller peut inclure cette information dans sa réponse HTTP
    /// pour que l'opérateur sache que le score est provisoire.
    /// </summary>
    public bool IsDefaultReview { get; }

    public AnalyzeTransactionResult(
        string transactionId,
        RiskScore score,
        bool isDefaultReview = false)
    {
        if (string.IsNullOrWhiteSpace(transactionId))
            throw new ArgumentException(
                "TransactionId ne peut pas être vide.", nameof(transactionId));

        TransactionId = transactionId;
        Score = score;
        IsDefaultReview = isDefaultReview;
    }
}