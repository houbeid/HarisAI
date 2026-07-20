using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Queries.GetTransactionHistory;

/// <summary>
/// Requête MediatR pour récupérer l'historique des transactions traitées.
/// Utilisée par AlertController (GET /transactions) — accès réservé aux
/// agents de conformité et superviseurs (JWT + rôle vérifié dans le Controller).
///
/// PÉRIMÈTRE : historique côté .NET (schéma fraud_backend) uniquement.
/// L'audit trail complet (toutes décisions, immuable) reste dans ml_audit
/// côté Python — ce n'est pas cette query qui y accède.
/// </summary>
public sealed record GetTransactionHistoryQuery : IRequest<GetTransactionHistoryResult>
{
    /// <summary>
    /// Filtre par opérateur — obligatoire sur ce site.
    /// Un agent de conformité ne voit que les transactions de son opérateur.
    /// </summary>
    public string OperatorCode { get; }

    /// <summary>Filtre par décision ML — null retourne toutes les décisions.</summary>
    public DecisionStatus? DecisionFilter { get; }

    /// <summary>
    /// Filtre par plage de dates — null retourne les 7 derniers jours par défaut.
    /// Limité à 90 jours maximum pour éviter des requêtes trop lourdes
    /// sur un PostgreSQL local avec ressources limitées (site bancaire on-premise).
    /// </summary>
    public DateTime? From { get; }
    public DateTime? To { get; }

    public int Page { get; }
    public int PageSize { get; }

    public GetTransactionHistoryQuery(
        string operatorCode,
        DecisionStatus? decisionFilter = null,
        DateTime? from = null,
        DateTime? to = null,
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

        // Validation de la plage de dates
        if (from.HasValue && to.HasValue && from > to)
            throw new ArgumentException(
                "La date de début ne peut pas être postérieure à la date de fin.",
                nameof(from));

        if (from.HasValue && to.HasValue &&
            (to.Value - from.Value).TotalDays > 90)
            throw new ArgumentException(
                "La plage de dates ne peut pas dépasser 90 jours. " +
                "Affiner les filtres ou exporter les données via un rapport.",
                nameof(to));

        OperatorCode = operatorCode.Trim().ToUpperInvariant();
        DecisionFilter = decisionFilter;
        From = from ?? DateTime.UtcNow.AddDays(-7);
        To = to ?? DateTime.UtcNow;
        Page = page;
        PageSize = pageSize;
    }
}

/// <summary>Résultat paginé retourné par GetTransactionHistoryHandler.</summary>
public sealed record GetTransactionHistoryResult
{
    public IReadOnlyList<Transaction> Transactions { get; }

    /// <summary>Résumé par décision — utile pour les graphiques Grafana/dashboard.</summary>
    public int TotalApprove { get; }
    public int TotalReview { get; }
    public int TotalBlock { get; }

    public int Page { get; }
    public int PageSize { get; }
    public DateTime From { get; }
    public DateTime To { get; }

    public GetTransactionHistoryResult(
        IReadOnlyList<Transaction> transactions,
        int totalApprove,
        int totalReview,
        int totalBlock,
        int page,
        int pageSize,
        DateTime from,
        DateTime to)
    {
        Transactions = transactions;
        TotalApprove = totalApprove;
        TotalReview = totalReview;
        TotalBlock = totalBlock;
        Page = page;
        PageSize = pageSize;
        From = from;
        To = to;
    }
}

/// <summary>
/// Handler de récupération de l'historique des transactions.
/// Retourne les transactions paginées avec un résumé par décision
/// pour alimenter les graphiques de fraud-dashboard sans requêtes supplémentaires.
/// </summary>
public sealed class GetTransactionHistoryHandler
    : IRequestHandler<GetTransactionHistoryQuery, GetTransactionHistoryResult>
{
    private readonly ITransactionRepository _transactionRepository;
    private readonly ILogger<GetTransactionHistoryHandler> _logger;

    public GetTransactionHistoryHandler(
        ITransactionRepository transactionRepository,
        ILogger<GetTransactionHistoryHandler> logger)
    {
        _transactionRepository = transactionRepository;
        _logger = logger;
    }

    public async Task<GetTransactionHistoryResult> Handle(
        GetTransactionHistoryQuery request,
        CancellationToken cancellationToken)
    {
        // Récupération des trois catégories de décision en parallèle
        // pour construire le résumé sans requêtes supplémentaires.
        // Si un filtre de décision est actif, les autres compteurs
        // retournent leur vraie valeur (pas filtrée) pour le résumé global.
        var transactionsTask = _transactionRepository.GetHistoryAsync(
            operatorCode: request.OperatorCode,
            decisionFilter: request.DecisionFilter,
            page: request.Page,
            pageSize: request.PageSize,
            cancellationToken: cancellationToken);

        var approveCountTask = _transactionRepository.GetHistoryAsync(
            operatorCode: request.OperatorCode,
            decisionFilter: DecisionStatus.Approve,
            page: 1,
            pageSize: 1,
            cancellationToken: cancellationToken);

        var reviewCountTask = _transactionRepository.GetHistoryAsync(
            operatorCode: request.OperatorCode,
            decisionFilter: DecisionStatus.Review,
            page: 1,
            pageSize: 1,
            cancellationToken: cancellationToken);

        var blockCountTask = _transactionRepository.GetHistoryAsync(
            operatorCode: request.OperatorCode,
            decisionFilter: DecisionStatus.Block,
            page: 1,
            pageSize: 1,
            cancellationToken: cancellationToken);

        await Task.WhenAll(
            transactionsTask,
            approveCountTask,
            reviewCountTask,
            blockCountTask);

        var transactions = await transactionsTask;

        _logger.LogDebug(
            "GetTransactionHistory — Operator={Operator} Decision={Decision} " +
            "From={From:yyyy-MM-dd} To={To:yyyy-MM-dd} " +
            "Page={Page} Count={Count}",
            request.OperatorCode,
            request.DecisionFilter?.ToString() ?? "toutes",
            request.From,
            request.To,
            request.Page,
            transactions.Count);

        return new GetTransactionHistoryResult(
            transactions: transactions,
            totalApprove: (await approveCountTask).Count,
            totalReview: (await reviewCountTask).Count,
            totalBlock: (await blockCountTask).Count,
            page: request.Page,
            pageSize: request.PageSize,
            from: request.From!.Value,
            to: request.To!.Value);
    }
}