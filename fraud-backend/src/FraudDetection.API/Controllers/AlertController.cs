using FraudDetection.Application.Commands.ValidateAlert;
using FraudDetection.Application.Queries.GetAlertById;
using FraudDetection.Application.Queries.GetAlerts;
using FraudDetection.Domain.Enums;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace FraudDetection.API.Controllers;

/// <summary>
/// Corps de requête pour valider une alerte — reçu depuis fraud-dashboard.
/// </summary>
public sealed record ValidateAlertRequest(
    AlertValidationAction Action,
    string? Note);

/// <summary>
/// Liste et validation des alertes par les agents de conformité.
/// Protégé par le schéma "Jwt" — jamais "Hmac" (réservé aux webhooks
/// opérateurs sur TransactionController).
///
/// Aucune restriction de rôle au niveau du Controller (contrairement à
/// ReportController, restreint à compliance_officer/supervisor pour la
/// génération de rapports STR) — tout agent authentifié peut consulter
/// et traiter les alertes, cohérent avec l'usage normal d'un dashboard
/// de conformité.
///
/// OPÉRATEUR TOUJOURS IMPLICITE : conformément à la topologie de déploiement
/// (un site = un opérateur), l'opérateur n'est jamais un paramètre choisi
/// par le client — il est lu depuis la configuration du site ("Operator:Code",
/// même clé que PendingMetricsPoller). Un agent connecté à un site Bankily
/// ne peut techniquement voir que les alertes Bankily, sans ambiguïté
/// possible dans l'URL.
///
/// POINT OUVERT : l'identité de l'agent (ReviewedBy) est lue depuis le
/// claim JWT "sub" (Subject, standard JWT) — la structure exacte des
/// claims dépend du mécanisme d'émission des tokens, pas encore défini
/// (voir JwtAuthenticationOptions). À ajuster si l'émetteur final utilise
/// un claim différent pour identifier l'agent.
/// </summary>
[ApiController]
[Route("alerts")]
[Authorize(AuthenticationSchemes = "Jwt")]
public sealed class AlertController : ControllerBase
{
    private readonly IMediator _mediator;
    private readonly IConfiguration _configuration;

    public AlertController(IMediator mediator, IConfiguration configuration)
    {
        _mediator = mediator;
        _configuration = configuration;
    }

    /// <summary>
    /// Liste les alertes du site, avec pagination. L'opérateur est toujours
    /// celui configuré pour ce déploiement — jamais un choix laissé au client.
    ///
    /// FILTRE MULTI-STATUTS : le paramètre "status" accepte plusieurs valeurs
    /// répétées dans la query string (liaison de tableau standard ASP.NET Core) —
    /// ex: ?status=Confirmed&amp;status=Dismissed pour le filtre "Traitées" du
    /// dashboard. Omis = comportement historique (Pending par défaut).
    /// ?status=Pending&amp;status=Confirmed&amp;status=Dismissed pour "Toutes".
    /// </summary>
    [HttpGet]
    public async Task<IActionResult> GetAlerts(
        [FromQuery] AlertStatus[]? status,
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 50,
        CancellationToken cancellationToken = default)
    {
        var operatorCode = _configuration["Operator:Code"];
        if (string.IsNullOrWhiteSpace(operatorCode))
        {
            // Configuration de site incomplète — ne devrait jamais arriver
            // en production (overlay Kustomize injecte toujours cette clé),
            // mais on ne veut pas non plus retourner silencieusement toutes
            // les alertes sans filtre en cas d'erreur de configuration.
            return StatusCode(
                StatusCodes.Status500InternalServerError,
                new { error = "site_operator_not_configured" });
        }

        var query = new GetAlertsQuery(
            statusFilter: status is { Length: > 0 } ? status : null,
            operatorCode: operatorCode,
            page: page,
            pageSize: pageSize);

        var result = await _mediator.Send(query, cancellationToken);

        return Ok(new
        {
            alerts = result.Alerts.Select(a => new
            {
                a.AlertId,
                a.TransactionId,
                a.Operator,
                Amount = a.Amount.Amount,
                Decision = a.Score.Decision.ToString(),
                a.Score.Score,
                a.Score.FraudType,
                Status = a.Status.ToString(),
                a.CreatedAt,
                a.ReviewedAt,
                a.ReviewedBy
            }),
            totalPending = result.TotalPending,
            totalProcessed = result.TotalProcessed,
            page = result.Page,
            pageSize = result.PageSize
        });
    }

    /// <summary>
    /// Récupère une alerte unique par son AlertId — comble le point ouvert 4
    /// réclamé par la session frontend : après un conflit 409 sur
    /// POST /alerts/{alertId}/validate (alerte déjà traitée par un autre
    /// agent), le dashboard peut relire l'état exact de CETTE alerte sans
    /// dépendre de la fenêtre de pagination de GET /alerts.
    ///
    /// GESTION D'ERREUR : AlertNotFoundException (404), levée par
    /// GetAlertByIdHandler, interceptée par GlobalExceptionMiddleware —
    /// pas de try/catch ici, cohérent avec les autres endpoints.
    /// </summary>
    [HttpGet("{alertId}")]
    public async Task<IActionResult> GetAlertById(
        string alertId,
        CancellationToken cancellationToken)
    {
        var alert = await _mediator.Send(
            new GetAlertByIdQuery(alertId), cancellationToken);

        return Ok(new
        {
            alert.AlertId,
            alert.TransactionId,
            alert.Operator,
            Amount = alert.Amount.Amount,
            Decision = alert.Score.Decision.ToString(),
            alert.Score.Score,
            alert.Score.FraudType,
            Status = alert.Status.ToString(),
            alert.CreatedAt,
            alert.ReviewedAt,
            alert.ReviewedBy
        });
    }

    /// <summary>
    /// Confirme ou écarte une alerte. Un Confirm déclenche automatiquement
    /// la génération d'un rapport STR (voir ValidateAlertHandler → MediatR
    /// → GenerateStrReportCommand) — pas d'appel séparé nécessaire ici.
    ///
    /// GESTION D'ERREUR : AlertNotFoundException (404) et
    /// AlertAlreadyProcessedException (409), levées par ValidateAlertHandler,
    /// sont interceptées par GlobalExceptionMiddleware — pas de try/catch ici.
    /// </summary>
    [HttpPost("{alertId}/validate")]
    public async Task<IActionResult> ValidateAlert(
        string alertId,
        [FromBody] ValidateAlertRequest request,
        CancellationToken cancellationToken)
    {
        // L'identité de l'agent vient du token JWT vérifié, jamais d'un champ
        // du corps de la requête — même principe que operator_code dans
        // TransactionController : ne jamais faire confiance à une identité
        // fournie par le client quand l'authentification en fournit déjà une.
        var reviewedBy = User.FindFirst("sub")?.Value ?? User.Identity?.Name;
        if (string.IsNullOrWhiteSpace(reviewedBy))
        {
            return Unauthorized();
        }

        var command = new ValidateAlertCommand(
            alertId: alertId,
            action: request.Action,
            reviewedBy: reviewedBy,
            note: request.Note);

        var result = await _mediator.Send(command, cancellationToken);

        return Ok(new
        {
            alertId = result.AlertId,
            action = result.ActionApplied.ToString(),
            strReportTriggered = result.StrReportTriggered
        });
    }
}