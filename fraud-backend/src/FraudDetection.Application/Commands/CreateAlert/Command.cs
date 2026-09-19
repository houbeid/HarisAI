using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.ValueObjects;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Commands.CreateAlert;

/// <summary>
/// Commande MediatR déclenchée par AnalyzeTransactionHandler (étape 9)
/// quand fraud-ml-service retourne une décision REVIEW ou BLOCK.
///
/// Séparée de AnalyzeTransactionCommand pour respecter le principe de
/// responsabilité unique — créer une alerte est une opération distincte
/// de l'analyse de la transaction, avec ses propres règles et son propre
/// audit. Cette séparation permet aussi de rejouer la création d'alerte
/// indépendamment si besoin (ex: alerte perdue lors d'un crash).
/// </summary>
public sealed record CreateAlertCommand : IRequest<CreateAlertResult>
{
    /// <summary>Identifiant FastAPI — format ALT-XXXXXXXXXXXXXXXX</summary>
    public string AlertId { get; }
    public string TransactionId { get; }
    public string OperatorCode { get; }
    public RiskScore Score { get; }

    /// <summary>
    /// Montant de la transaction ayant déclenché l'alerte — copié depuis
    /// Transaction.Amount par l'appelant (AnalyzeTransactionHandler ou
    /// PendingTransactionWorker). Voir Alert.Amount (Domain).
    /// </summary>
    public Money Amount { get; }

    public CreateAlertCommand(
        string alertId,
        string transactionId,
        string operatorCode,
        RiskScore score,
        Money amount)
    {
        if (string.IsNullOrWhiteSpace(alertId))
            throw new ArgumentException("AlertId ne peut pas être vide.", nameof(alertId));

        if (string.IsNullOrWhiteSpace(transactionId))
            throw new ArgumentException("TransactionId ne peut pas être vide.", nameof(transactionId));

        if (string.IsNullOrWhiteSpace(operatorCode))
            throw new ArgumentException("OperatorCode ne peut pas être vide.", nameof(operatorCode));

        ArgumentNullException.ThrowIfNull(score);
        ArgumentNullException.ThrowIfNull(amount);

        // Guard : cette commande ne doit jamais être créée pour APPROVE
        if (!score.RequiresHumanReview)
            throw new ArgumentException(
                $"CreateAlertCommand ne peut être créé que pour REVIEW ou BLOCK. " +
                $"Décision reçue : {score.Decision}",
                nameof(score));

        AlertId = alertId.Trim();
        TransactionId = transactionId.Trim();
        OperatorCode = operatorCode.Trim().ToUpperInvariant();
        Score = score;
        Amount = amount;
    }
}

/// <summary>Résultat retourné après création de l'alerte.</summary>
public sealed record CreateAlertResult
{
    public Guid AlertLocalId { get; }
    public bool AlreadyExisted { get; }

    public CreateAlertResult(Guid alertLocalId, bool alreadyExisted = false)
    {
        AlertLocalId = alertLocalId;
        AlreadyExisted = alreadyExisted;
    }
}

/// <summary>
/// Handler de création d'alerte.
/// Vérifie l'idempotence avant de persister — un retry de webhook
/// ne doit pas créer deux alertes pour la même transaction.
/// </summary>
public sealed class CreateAlertHandler
    : IRequestHandler<CreateAlertCommand, CreateAlertResult>
{
    private readonly IAlertRepository _alertRepository;
    private readonly IAlertNotifier _alertNotifier;
    private readonly ILogger<CreateAlertHandler> _logger;

    public CreateAlertHandler(
        IAlertRepository alertRepository,
        IAlertNotifier alertNotifier,
        ILogger<CreateAlertHandler> logger)
    {
        _alertRepository = alertRepository;
        _alertNotifier = alertNotifier;
        _logger = logger;
    }

    public async Task<CreateAlertResult> Handle(
        CreateAlertCommand request,
        CancellationToken cancellationToken)
    {
        // ── Idempotence — vérifier si une alerte existe déjà ─────────────────
        // Cas normal lors d'un retry opérateur : la même transaction revient,
        // FastAPI retourne le même AlertId (idempotence côté Python), et on
        // ne doit pas créer une deuxième alerte côté .NET.
        var existing = await _alertRepository.GetByTransactionIdAsync(
            request.TransactionId, cancellationToken);

        if (existing is not null)
        {
            _logger.LogWarning(
                "Alerte déjà existante pour TransactionId={TransactionId} " +
                "AlertId={AlertId} — création ignorée (idempotence).",
                request.TransactionId,
                request.AlertId);

            // Pas de nouvelle notification SignalR ici — l'agent a déjà été
            // notifié lors de la création originale de cette alerte.
            return new CreateAlertResult(existing.Id, alreadyExisted: true);
        }

        // ── Créer et persister la nouvelle alerte ─────────────────────────────
        var alert = new Alert(
            alertId: request.AlertId,
            transactionId: request.TransactionId,
            @operator: request.OperatorCode,
            score: request.Score,
            amount: request.Amount,
            createdAt: DateTime.UtcNow);

        await _alertRepository.SaveAsync(alert, cancellationToken);

        _logger.LogInformation(
            "Alerte créée — AlertId={AlertId} TransactionId={TransactionId} " +
            "Decision={Decision} FraudType={FraudType} Operator={Operator}",
            alert.AlertId,
            alert.TransactionId,
            alert.Score.Decision,
            alert.Score.FraudType,
            alert.Operator);

        // ── Notifier les agents connectés en temps réel ───────────────────────
        // Appelé APRÈS SaveAsync réussi, jamais avant — un agent ne doit
        // jamais être notifié d'une alerte qui n'existe pas encore en base.
        // IAlertNotifier garantit ne jamais lever d'exception (voir son
        // interface) — un échec de notification ne remet jamais en cause
        // la création de l'alerte, déjà persistée avec succès à ce stade.
        await _alertNotifier.NotifyNewAlertAsync(
            alertId: alert.AlertId,
            transactionId: alert.TransactionId,
            decision: alert.Score.Decision.ToString(),
            score: alert.Score.Score,
            fraudType: alert.Score.FraudType,
            cancellationToken: cancellationToken);

        return new CreateAlertResult(alert.Id);
    }
}