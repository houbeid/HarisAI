using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Queries.GetAlerts;

/// <summary>
/// Requête MediatR pour récupérer les alertes depuis fraud-dashboard.
/// Utilisée par AlertController (GET /alerts) — accès réservé aux agents
/// de conformité et superviseurs (JWT + rôle vérifié dans le Controller).
///
/// Retourne uniquement les alertes du site local (un déploiement = un opérateur).
/// Pas de requête cross-opérateur — chaque site voit uniquement ses alertes.
/// </summary>
public sealed record GetAlertsQuery : IRequest<GetAlertsResult>
{
    /// <summary>
    /// Filtre par un ou plusieurs statuts. Null = défaut Pending (comportement
    /// historique du dashboard pour les agents). Une collection explicite
    /// permet de combiner plusieurs statuts en un seul appel — notamment le
    /// filtre "Traitées" du dashboard, qui combine Confirmed + Dismissed
    /// (voir AlertController pour le mapping exact des query params).
    /// </summary>
    public IReadOnlyCollection<AlertStatus>? StatusFilter { get; }

    /// <summary>
    /// Filtre par opérateur — null retourne toutes les alertes du site.
    /// Utile pour les superviseurs qui supervisent plusieurs opérateurs
    /// sur un site mutualisé (cas rare mais prévu dans le registre).
    /// </summary>
    public string? OperatorCode { get; }

    public int Page { get; }
    public int PageSize { get; }

    public GetAlertsQuery(
        IReadOnlyCollection<AlertStatus>? statusFilter = null,
        string? operatorCode = null,
        int page = 1,
        int pageSize = 50)
    {
        if (page < 1)
            throw new ArgumentException("Page doit être supérieure à 0.", nameof(page));

        if (pageSize is < 1 or > 200)
            throw new ArgumentException(
                "PageSize doit être entre 1 et 200.", nameof(pageSize));

        StatusFilter = statusFilter;
        OperatorCode = operatorCode?.Trim().ToUpperInvariant();
        Page = page;
        PageSize = pageSize;
    }
}

/// <summary>
/// Résultat paginé retourné par GetAlertsHandler.
/// TotalPending et TotalProcessed sont TOUJOURS calculés sur l'ensemble du
/// site (indépendamment du StatusFilter demandé) — ce sont des compteurs
/// globaux pour les badges du dashboard, pas des totaux liés à la page
/// actuellement affichée.
/// </summary>
public sealed record GetAlertsResult
{
    public IReadOnlyList<Alert> Alerts { get; }
    public int TotalPending { get; }

    /// <summary>
    /// Nombre total d'alertes Confirmed + Dismissed, tous statuts "traités"
    /// confondus. Ajouté pour le badge "X alertes traitées" du dashboard —
    /// absent avant cette version, réclamé par la session frontend.
    /// </summary>
    public int TotalProcessed { get; }

    public int Page { get; }
    public int PageSize { get; }

    public GetAlertsResult(
        IReadOnlyList<Alert> alerts,
        int totalPending,
        int totalProcessed,
        int page,
        int pageSize)
    {
        Alerts = alerts;
        TotalPending = totalPending;
        TotalProcessed = totalProcessed;
        Page = page;
        PageSize = pageSize;
    }
}

/// <summary>
/// Handler de récupération des alertes.
/// Retourne les alertes paginées + les compteurs Pending et Processed
/// pour que fraud-dashboard affiche les badges de charge de travail
/// sans requêtes séparées.
/// </summary>
public sealed class GetAlertsHandler
    : IRequestHandler<GetAlertsQuery, GetAlertsResult>
{
    private static readonly IReadOnlyCollection<AlertStatus> ProcessedStatuses =
        new[] { AlertStatus.Confirmed, AlertStatus.Dismissed };

    private readonly IAlertRepository _alertRepository;
    private readonly ILogger<GetAlertsHandler> _logger;

    public GetAlertsHandler(
        IAlertRepository alertRepository,
        ILogger<GetAlertsHandler> logger)
    {
        _alertRepository = alertRepository;
        _logger = logger;
    }

    public async Task<GetAlertsResult> Handle(
        GetAlertsQuery request,
        CancellationToken cancellationToken)
    {
        // Défaut historique préservé : pas de filtre explicite = Pending.
        var effectiveStatuses = request.StatusFilter
            ?? new[] { AlertStatus.Pending };

        // Trois requêtes en parallèle — la liste filtrée, le badge Pending,
        // et le nouveau badge Processed — pour limiter la latence dashboard.
        var alertsTask = _alertRepository.GetByStatusAsync(
            statuses: effectiveStatuses,
            operatorCode: request.OperatorCode,
            page: request.Page,
            pageSize: request.PageSize,
            cancellationToken: cancellationToken);

        var pendingCountTask = _alertRepository.CountPendingAsync(
            operatorCode: request.OperatorCode ?? string.Empty,
            cancellationToken: cancellationToken);

        var processedCountTask = _alertRepository.CountByStatusesAsync(
            statuses: ProcessedStatuses,
            operatorCode: request.OperatorCode,
            cancellationToken: cancellationToken);

        await Task.WhenAll(alertsTask, pendingCountTask, processedCountTask);

        var alerts = await alertsTask;
        var totalPending = await pendingCountTask;
        var totalProcessed = await processedCountTask;

        _logger.LogDebug(
            "GetAlerts — Statuses={Statuses} Operator={Operator} " +
            "Page={Page} PageSize={PageSize} Count={Count} " +
            "TotalPending={TotalPending} TotalProcessed={TotalProcessed}",
            string.Join(",", effectiveStatuses),
            request.OperatorCode ?? "tous",
            request.Page,
            request.PageSize,
            alerts.Count,
            totalPending,
            totalProcessed);

        return new GetAlertsResult(
            alerts: alerts,
            totalPending: totalPending,
            totalProcessed: totalProcessed,
            page: request.Page,
            pageSize: request.PageSize);
    }
}