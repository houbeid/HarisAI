using FraudDetection.Application.Commands.GenerateStrReport;
using FraudDetection.Application.Exceptions;
using FraudDetection.Application.Interfaces;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Commands.ValidateAlert;

/// <summary>
/// Action que l'agent de conformité applique sur une alerte Pending.
/// </summary>
public enum AlertValidationAction
{
    /// <summary>Fraude confirmée — déclenche la génération d'un rapport STR vers la BCM</summary>
    Confirm,

    /// <summary>Faux positif écarté — alerte fermée sans rapport STR</summary>
    Dismiss
}

/// <summary>
/// Commande MediatR déclenchée par AlertController quand un agent de conformité
/// valide ou écarte une alerte depuis fraud-dashboard.
///
/// AUTORISATIONS (vérifiées dans AlertController, pas ici) :
///   - Confirm et Dismiss : rôle compliance_officer ou supervisor
///   - Un agent ne peut valider que les alertes de son opérateur
///     (filtrage par OperatorCode côté Controller via les claims JWT)
/// </summary>
public sealed record ValidateAlertCommand : IRequest<ValidateAlertResult>
{
    /// <summary>Identifiant FastAPI de l'alerte — format ALT-XXXXXXXXXXXXXXXX</summary>
    public string AlertId { get; }

    /// <summary>Action appliquée par l'agent</summary>
    public AlertValidationAction Action { get; }

    /// <summary>Identifiant de l'agent (email ou username extrait du JWT)</summary>
    public string ReviewedBy { get; }

    /// <summary>Note optionnelle justifiant la décision — utile pour l'audit BCM</summary>
    public string? Note { get; }

    public ValidateAlertCommand(
        string alertId,
        AlertValidationAction action,
        string reviewedBy,
        string? note = null)
    {
        if (string.IsNullOrWhiteSpace(alertId))
            throw new ArgumentException("AlertId ne peut pas être vide.", nameof(alertId));

        if (string.IsNullOrWhiteSpace(reviewedBy))
            throw new ArgumentException("ReviewedBy ne peut pas être vide.", nameof(reviewedBy));

        AlertId = alertId.Trim();
        Action = action;
        ReviewedBy = reviewedBy.Trim();
        Note = note?.Trim();
    }
}

/// <summary>Résultat retourné après validation de l'alerte.</summary>
public sealed record ValidateAlertResult
{
    public string AlertId { get; }
    public AlertValidationAction ActionApplied { get; }

    /// <summary>
    /// Vrai si un rapport STR a été déclenché vers la BCM.
    /// Présent uniquement pour les Confirm — toujours false pour Dismiss.
    /// </summary>
    public bool StrReportTriggered { get; }

    public ValidateAlertResult(
        string alertId,
        AlertValidationAction actionApplied,
        bool strReportTriggered = false)
    {
        AlertId = alertId;
        ActionApplied = actionApplied;
        StrReportTriggered = strReportTriggered;
    }
}

/// <summary>
/// Handler de validation d'alerte.
/// Applique la décision de l'agent sur l'entité Alert du domaine,
/// persiste le changement, et déclenche le rapport STR si Confirmed.
/// </summary>
public sealed class ValidateAlertHandler
    : IRequestHandler<ValidateAlertCommand, ValidateAlertResult>
{
    private readonly IAlertRepository _alertRepository;
    private readonly IMediator _mediator;
    private readonly ILogger<ValidateAlertHandler> _logger;

    public ValidateAlertHandler(
        IAlertRepository alertRepository,
        IMediator mediator,
        ILogger<ValidateAlertHandler> logger)
    {
        _alertRepository = alertRepository;
        _mediator = mediator;
        _logger = logger;
    }

    public async Task<ValidateAlertResult> Handle(
        ValidateAlertCommand request,
        CancellationToken cancellationToken)
    {
        // ── Récupérer l'alerte ────────────────────────────────────────────────
        var alert = await _alertRepository.GetByAlertIdAsync(
            request.AlertId, cancellationToken);

        if (alert is null)
        {
            _logger.LogError(
                "Alerte introuvable — AlertId={AlertId} ReviewedBy={ReviewedBy}",
                request.AlertId,
                request.ReviewedBy);

            throw new AlertNotFoundException(request.AlertId);
        }

        // ── Appliquer la décision de l'agent ─────────────────────────────────
        // Alert.Confirm() et Alert.Dismiss() lèvent InvalidOperationException
        // si l'alerte n'est plus Pending — règle métier du domaine, seule
        // source de vérité. Ce Handler traduit cet échec en
        // AlertAlreadyProcessedException, un type exploitable par l'API
        // (mappé vers 409 Conflict par GlobalExceptionMiddleware) sans
        // dupliquer la règle elle-même.
        try
        {
            switch (request.Action)
            {
                case AlertValidationAction.Confirm:
                    alert.Confirm(request.ReviewedBy, request.Note);
                    break;

                case AlertValidationAction.Dismiss:
                    alert.Dismiss(request.ReviewedBy, request.Note);
                    break;

                default:
                    throw new ArgumentOutOfRangeException(
                        nameof(request.Action),
                        $"Action non supportée : {request.Action}");
            }
        }
        catch (InvalidOperationException ex)
        {
            _logger.LogWarning(
                "Alerte déjà traitée — AlertId={AlertId} Status={Status} " +
                "TentativeReviewedBy={ReviewedBy}",
                alert.AlertId, alert.Status, request.ReviewedBy);

            throw new AlertAlreadyProcessedException(request.AlertId, ex);
        }

        // ── Persister le changement de statut ─────────────────────────────────
        await _alertRepository.UpdateAsync(alert, cancellationToken);

        _logger.LogInformation(
            "Alerte {Action} — AlertId={AlertId} ReviewedBy={ReviewedBy} " +
            "TransactionId={TransactionId} Note={Note}",
            request.Action,
            alert.AlertId,
            request.ReviewedBy,
            alert.TransactionId,
            request.Note ?? "aucune");

        // ── Déclencher le rapport STR si fraude confirmée ─────────────────────
        // Un rapport STR (Suspicious Transaction Report) est obligatoire
        // pour toute fraude confirmée — exigence réglementaire BCM.
        // Déclenché via MediatR pour garder ce Handler focalisé sur
        // la validation de l'alerte, pas sur la génération du rapport.
        bool strReportTriggered = false;
        if (alert.RequiresStrReport)
        {
            await _mediator.Send(
                new GenerateStrReportCommand(
                    alertId: alert.AlertId,
                    transactionId: alert.TransactionId,
                    operatorCode: alert.Operator,
                    score: alert.Score,
                    confirmedBy: request.ReviewedBy,
                    note: request.Note),
                cancellationToken);

            strReportTriggered = true;
        }

        return new ValidateAlertResult(
            alertId: alert.AlertId,
            actionApplied: request.Action,
            strReportTriggered: strReportTriggered);
    }
}