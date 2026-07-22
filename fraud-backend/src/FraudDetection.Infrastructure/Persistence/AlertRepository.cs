using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;

namespace FraudDetection.Infrastructure.Persistence;

/// <summary>
/// Implémentation de IAlertRepository avec EF Core / PostgreSQL.
/// Responsable du mapping bidirectionnel Alert (Domain) vers AlertRecord (persistance).
///
/// Le Domain reste pur — cette classe est la SEULE frontière où Alert
/// (avec ses règles métier : Confirm(), Dismiss(), guards du constructeur)
/// rencontre EF Core.
/// </summary>
public sealed class AlertRepository : IAlertRepository
{
    private readonly AppDbContext _dbContext;

    public AlertRepository(AppDbContext dbContext)
    {
        _dbContext = dbContext;
    }

    public async Task SaveAsync(Alert alert, CancellationToken cancellationToken = default)
    {
        var record = ToRecord(alert);
        _dbContext.Alerts.Add(record);
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task<Alert?> GetByAlertIdAsync(
        string alertId, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.Alerts
            .AsNoTracking()
            .FirstOrDefaultAsync(a => a.AlertId == alertId, cancellationToken);

        return record is null ? null : ToDomain(record);
    }

    public async Task<Alert?> GetByTransactionIdAsync(
        string transactionId, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.Alerts
            .AsNoTracking()
            .FirstOrDefaultAsync(a => a.TransactionId == transactionId, cancellationToken);

        return record is null ? null : ToDomain(record);
    }

    public async Task<IReadOnlyList<Alert>> GetByStatusAsync(
        AlertStatus status,
        string? operatorCode = null,
        int page = 1,
        int pageSize = 50,
        CancellationToken cancellationToken = default)
    {
        var query = _dbContext.Alerts
            .AsNoTracking()
            .Where(a => a.Status == status.ToString());

        if (!string.IsNullOrWhiteSpace(operatorCode))
        {
            query = query.Where(a => a.Operator == operatorCode);
        }

        var records = await query
            .OrderByDescending(a => a.CreatedAt)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync(cancellationToken);

        return records.Select(ToDomain).ToList();
    }

    public async Task UpdateAsync(Alert alert, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.Alerts
            .FirstOrDefaultAsync(a => a.AlertId == alert.AlertId, cancellationToken);

        if (record is null)
        {
            // Signale un bug de cohérence — l'appelant (ValidateAlertHandler)
            // a déjà vérifié l'existence via GetByAlertIdAsync avant d'appeler
            // UpdateAsync. Si on arrive ici, quelque chose a supprimé la ligne
            // entre les deux appels, ou il y a une incohérence applicative.
            throw new InvalidOperationException(
                $"Impossible de mettre à jour l'alerte {alert.AlertId} — " +
                $"introuvable en base. Incohérence applicative à investiguer.");
        }

        // Mise à jour des seuls champs mutables du cycle de vie —
        // Score, TransactionId, Operator ne changent jamais après création.
        record.Status = alert.Status.ToString();
        record.ReviewedAt = alert.ReviewedAt;
        record.ReviewedBy = alert.ReviewedBy;
        record.ReviewNote = alert.ReviewNote;

        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task<int> CountPendingAsync(
        string operatorCode, CancellationToken cancellationToken = default)
    {
        return await _dbContext.Alerts
            .AsNoTracking()
            .Where(a => a.Operator == operatorCode && a.Status == AlertStatus.Pending.ToString())
            .CountAsync(cancellationToken);
    }

    // ── Mapping Alert (Domain) vers AlertRecord ───────────────────────────────

    private static AlertRecord ToRecord(Alert alert) => new()
    {
        Id = alert.Id,
        AlertId = alert.AlertId,
        TransactionId = alert.TransactionId,
        Operator = alert.Operator,
        Score = alert.Score.Score,
        Decision = alert.Score.Decision.ToString(),
        FraudType = alert.Score.FraudType,
        XgboostScore = alert.Score.XgboostScore,
        IsolationScore = alert.Score.IsolationScore,
        TftScore = alert.Score.TftScore,
        GnnScore = alert.Score.GnnScore,
        Status = alert.Status.ToString(),
        CreatedAt = alert.CreatedAt,
        ReviewedAt = alert.ReviewedAt,
        ReviewedBy = alert.ReviewedBy,
        ReviewNote = alert.ReviewNote
    };

    // ── Mapping AlertRecord vers Alert (Domain) ───────────────────────────────

    /// <summary>
    /// Reconstruit l'entité Domain depuis le Record de persistance.
    /// Utilise le constructeur public de Alert (toujours Pending à la création),
    /// puis rejoue Confirm()/Dismiss() si le Record indique un statut différent —
    /// garantit que les mêmes guards métier s'appliquent qu'à la création initiale,
    /// pas de contournement des règles du Domain via une reconstruction "silencieuse".
    /// </summary>
    private static Alert ToDomain(AlertRecord record)
    {
        var score = new RiskScore(
            score: record.Score,
            decision: Enum.Parse<DecisionStatus>(record.Decision),
            fraudType: record.FraudType,
            alertId: record.AlertId,
            xgboostScore: record.XgboostScore,
            isolationScore: record.IsolationScore,
            tftScore: record.TftScore,
            gnnScore: record.GnnScore);

        var alert = new Alert(
            alertId: record.AlertId,
            transactionId: record.TransactionId,
            @operator: record.Operator,
            score: score,
            createdAt: record.CreatedAt);

        var status = Enum.Parse<AlertStatus>(record.Status);

        if (status == AlertStatus.Confirmed)
        {
            alert.Confirm(record.ReviewedBy!, record.ReviewNote);
        }
        else if (status == AlertStatus.Dismissed)
        {
            alert.Dismiss(record.ReviewedBy!, record.ReviewNote);
        }

        return alert;
    }
}