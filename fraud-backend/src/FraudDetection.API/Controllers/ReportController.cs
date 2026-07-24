using FraudDetection.Application.Queries.GetStrReports;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace FraudDetection.API.Controllers;

/// <summary>
/// Consultation des rapports STR (Suspicious Transaction Report) déjà
/// générés. Protégé par le schéma "Jwt" ET restreint aux rôles
/// compliance_officer et supervisor — contrairement à AlertController
/// (accessible à tout agent authentifié), la consultation des rapports
/// STR est une action réglementairement sensible.
///
/// LECTURE SEULE : aucun endpoint de création ici — un rapport STR est
/// toujours généré automatiquement par ValidateAlertHandler suite à
/// Alert.Confirm(), jamais déclenché manuellement par un agent via l'API.
///
/// OPÉRATEUR TOUJOURS IMPLICITE : même principe que AlertController —
/// lu depuis la configuration du site ("Operator:Code"), jamais un
/// paramètre choisi par le client.
///
/// POINT OUVERT : la transmission effective à la BCM (IBcmReportingService)
/// n'existe pas encore — chaque rapport retourné ici a Transmitted=false
/// en pratique tant que ce service n'est pas implémenté. Ce Controller
/// permet au moins aux agents de consulter ce qui a été généré localement.
/// </summary>
[ApiController]
[Route("reports")]
[Authorize(AuthenticationSchemes = "Jwt", Roles = "compliance_officer,supervisor")]
public sealed class ReportController : ControllerBase
{
    private readonly IMediator _mediator;
    private readonly IConfiguration _configuration;

    public ReportController(IMediator mediator, IConfiguration configuration)
    {
        _mediator = mediator;
        _configuration = configuration;
    }

    /// <summary>
    /// Liste les rapports STR générés pour l'opérateur du site, triés par
    /// date de génération décroissante, avec pagination.
    /// </summary>
    [HttpGet]
    public async Task<IActionResult> GetReports(
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 50,
        CancellationToken cancellationToken = default)
    {
        var operatorCode = _configuration["Operator:Code"];
        if (string.IsNullOrWhiteSpace(operatorCode))
        {
            return StatusCode(
                StatusCodes.Status500InternalServerError,
                new { error = "site_operator_not_configured" });
        }

        var query = new GetStrReportsQuery(
            operatorCode: operatorCode,
            page: page,
            pageSize: pageSize);

        var result = await _mediator.Send(query, cancellationToken);

        return Ok(new
        {
            reports = result.Reports.Select(r => new
            {
                r.ReportId,
                r.AlertId,
                r.TransactionId,
                r.OperatorCode,
                r.FraudType,
                r.RiskScore,
                r.Decision,
                r.ConfirmedBy,
                r.AgentNote,
                r.GeneratedAt
            }),
            page = result.Page,
            pageSize = result.PageSize
        });
    }
}