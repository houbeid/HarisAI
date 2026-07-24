using FraudDetection.Application.Commands.GenerateStrReport;
using FraudDetection.Application.Interfaces;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Queries.GetStrReports;

/// <summary>
/// Requête MediatR pour récupérer l'historique des rapports STR d'un
/// opérateur. Utilisée par ReportController (GET /reports) — accès
/// réservé aux rôles compliance_officer et supervisor.
///
/// OperatorCode obligatoire — même principe que AlertController :
/// toujours celui du site (lu depuis la configuration par le Controller,
/// jamais un choix laissé au client), cohérent avec la topologie
/// un site = un opérateur.
/// </summary>
public sealed record GetStrReportsQuery : IRequest<GetStrReportsResult>
{
    public string OperatorCode { get; }
    public int Page { get; }
    public int PageSize { get; }

    public GetStrReportsQuery(
        string operatorCode,
        int page = 1,
        int pageSize = 50)
    {
        if (string.IsNullOrWhiteSpace(operatorCode))
            throw new ArgumentException(
                "OperatorCode est obligatoire.", nameof(operatorCode));

        if (page < 1)
            throw new ArgumentException(
                "Page doit être supérieure à 0.", nameof(page));

        if (pageSize is < 1 or > 200)
            throw new ArgumentException(
                "PageSize doit être entre 1 et 200.", nameof(pageSize));

        OperatorCode = operatorCode.Trim().ToUpperInvariant();
        Page = page;
        PageSize = pageSize;
    }
}

/// <summary>Résultat paginé retourné par GetStrReportsHandler.</summary>
public sealed record GetStrReportsResult
{
    public IReadOnlyList<StrReportData> Reports { get; }
    public int Page { get; }
    public int PageSize { get; }

    public GetStrReportsResult(
        IReadOnlyList<StrReportData> reports,
        int page,
        int pageSize)
    {
        Reports = reports;
        Page = page;
        PageSize = pageSize;
    }
}

/// <summary>
/// Handler de récupération de l'historique des rapports STR.
/// Délègue entièrement à IStrReportRepository.GetHistoryAsync — pas de
/// logique métier supplémentaire, cohérent avec le rôle d'une Query
/// (lecture pure, jamais de mutation).
/// </summary>
public sealed class GetStrReportsHandler
    : IRequestHandler<GetStrReportsQuery, GetStrReportsResult>
{
    private readonly IStrReportRepository _strReportRepository;
    private readonly ILogger<GetStrReportsHandler> _logger;

    public GetStrReportsHandler(
        IStrReportRepository strReportRepository,
        ILogger<GetStrReportsHandler> logger)
    {
        _strReportRepository = strReportRepository;
        _logger = logger;
    }

    public async Task<GetStrReportsResult> Handle(
        GetStrReportsQuery request,
        CancellationToken cancellationToken)
    {
        var reports = await _strReportRepository.GetHistoryAsync(
            operatorCode: request.OperatorCode,
            page: request.Page,
            pageSize: request.PageSize,
            cancellationToken: cancellationToken);

        _logger.LogDebug(
            "GetStrReports — Operator={Operator} Page={Page} Count={Count}",
            request.OperatorCode, request.Page, reports.Count);

        return new GetStrReportsResult(
            reports: reports,
            page: request.Page,
            pageSize: request.PageSize);
    }
}