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
    /// Filtre par statut — null retourne toutes les alertes.
    /// Le dashboard affiche par défaut les Pending pour les agents,
    /// et toutes les alertes pour les superviseurs.
    /// </summary>
    public AlertStatus? StatusFilter { get; }

    /// <summary>
    /// Filtre par opérateur — null retourne toutes les alertes du site.
    /// Utile pour les superviseurs qui supervisent plusieurs opérateurs
    /// sur un site mutualisé (cas rare mais prévu dans le registre).
    /// </summary>
    public string? OperatorCode { get; }

    public int Page { get; }
    public int PageSize { get; }

    public GetAlertsQuery(
        AlertStatus? statusFilter = null,
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

/// <summary>Résultat paginé retourné par GetAlertsHandler.</summary>
public sealed record GetAlertsResult
{
    public IReadOnlyList<Alert> Alerts { get; }
    public int TotalPending { get; }
    public int Page { get; }
    public int PageSize { get; }

    public GetAlertsResult(
        IReadOnlyList<Alert> alerts,
        int totalPending,
        int page,
        int pageSize)
    {
        Alerts = alerts;
        TotalPending = totalPending;
        Page = page;
        PageSize = pageSize;
    }
}

/// <summary>
/// Handler de récupération des alertes.
/// Retourne les alertes paginées + le compteur Pending
/// pour que fraud-dashboard affiche le badge de charge de travail
/// sans une requête séparée.
/// </summary>
public sealed class GetAlertsHandler
    : IRequestHandler<GetAlertsQuery, GetAlertsResult>
{
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
        // Récupération des alertes et du compteur Pending en parallèle
        // pour limiter la latence de la réponse dashboard.
        var alertsTask = _alertRepository.GetByStatusAsync(
            status: request.StatusFilter ?? AlertStatus.Pending,
            operatorCode: request.OperatorCode,
            page: request.Page,
            pageSize: request.PageSize,
            cancellationToken: cancellationToken);

        var pendingCountTask = _alertRepository.CountPendingAsync(
            operatorCode: request.OperatorCode ?? string.Empty,
            cancellationToken: cancellationToken);

        await Task.WhenAll(alertsTask, pendingCountTask);

        var alerts = await alertsTask;
        var totalPending = await pendingCountTask;

        _logger.LogDebug(
            "GetAlerts — Status={Status} Operator={Operator} " +
            "Page={Page} PageSize={PageSize} Count={Count} TotalPending={TotalPending}",
            request.StatusFilter,
            request.OperatorCode ?? "tous",
            request.Page,
            request.PageSize,
            alerts.Count,
            totalPending);

        return new GetAlertsResult(
            alerts: alerts,
            totalPending: totalPending,
            page: request.Page,
            pageSize: request.PageSize);
    }
}