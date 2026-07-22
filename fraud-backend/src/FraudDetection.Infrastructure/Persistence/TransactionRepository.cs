using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;

namespace FraudDetection.Infrastructure.Persistence;

/// <summary>
/// Implémentation de ITransactionRepository avec EF Core / PostgreSQL.
/// Responsable du mapping bidirectionnel Transaction (Domain) vers TransactionRecord.
///
/// PÉRIMÈTRE : historique .NET (schéma fraud_backend) — distinct de l'audit trail
/// immuable ml_audit géré côté Python (PostgresAuditStore).
/// </summary>
public sealed class TransactionRepository : ITransactionRepository
{
    private readonly AppDbContext _dbContext;

    public TransactionRepository(AppDbContext dbContext)
    {
        _dbContext = dbContext;
    }

    public async Task SaveAsync(
        Transaction transaction, CancellationToken cancellationToken = default)
    {
        var record = ToRecord(transaction);
        _dbContext.Transactions.Add(record);
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task UpdateScoreAsync(
        string transactionId, RiskScore score, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.Transactions
            .FirstOrDefaultAsync(t => t.TransactionId == transactionId, cancellationToken);

        if (record is null)
        {
            throw new InvalidOperationException(
                $"Impossible de mettre à jour le score de {transactionId} — " +
                $"transaction introuvable en base. SaveAsync aurait dû être appelé avant.");
        }

        record.Score = score.Score;
        record.Decision = score.Decision.ToString();
        record.FraudType = score.FraudType;
        record.AlertId = score.AlertId;
        record.XgboostScore = score.XgboostScore;
        record.IsolationScore = score.IsolationScore;
        record.TftScore = score.TftScore;
        record.GnnScore = score.GnnScore;
        record.InferenceTimeMs = score.InferenceTimeMs;
        record.ModelVersion = score.ModelVersion;
        record.IsDefaultReview = score.FraudType == "UNAVAILABLE";
        record.ScoredAt = DateTime.UtcNow;

        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task UpdateNotificationStatusAsync(
        string transactionId,
        NotificationStatus status,
        CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.Transactions
            .FirstOrDefaultAsync(t => t.TransactionId == transactionId, cancellationToken);

        if (record is null)
        {
            throw new InvalidOperationException(
                $"Impossible de mettre à jour le statut de notification de {transactionId} — " +
                $"transaction introuvable en base.");
        }

        record.NotificationStatus = status.ToString();
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task<Transaction?> GetByIdAsync(
        string transactionId, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.Transactions
            .AsNoTracking()
            .FirstOrDefaultAsync(t => t.TransactionId == transactionId, cancellationToken);

        return record is null ? null : ToDomain(record);
    }

    public async Task<IReadOnlyList<Transaction>> GetHistoryAsync(
        string operatorCode,
        DecisionStatus? decisionFilter = null,
        int page = 1,
        int pageSize = 50,
        CancellationToken cancellationToken = default)
    {
        var query = _dbContext.Transactions
            .AsNoTracking()
            .Where(t => t.Operator == operatorCode);

        if (decisionFilter.HasValue)
        {
            query = query.Where(t => t.Decision == decisionFilter.Value.ToString());
        }

        var records = await query
            .OrderByDescending(t => t.Timestamp)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync(cancellationToken);

        return records.Select(ToDomain).ToList();
    }

    public async Task<IReadOnlyList<Transaction>> GetFailedNotificationsAsync(
        string operatorCode, CancellationToken cancellationToken = default)
    {
        var records = await _dbContext.Transactions
            .AsNoTracking()
            .Where(t => t.Operator == operatorCode
                     && t.NotificationStatus == NotificationStatus.Failed.ToString())
            .OrderBy(t => t.ReceivedAt) // FIFO — les plus anciens échecs en premier
            .ToListAsync(cancellationToken);

        return records.Select(ToDomain).ToList();
    }

    // ── Mapping Transaction (Domain) vers TransactionRecord ───────────────────

    private static TransactionRecord ToRecord(Transaction transaction) => new()
    {
        TransactionId = transaction.TransactionId,
        ClientToken = transaction.ClientToken.Value,
        Amount = transaction.Amount.Amount,
        Currency = transaction.Amount.Currency,
        Channel = transaction.Channel.ToString(),
        Zone = transaction.Zone,
        Operator = transaction.Operator,
        DeviceId = transaction.DeviceId.Value,
        SimChanged72h = transaction.SimChanged72h,
        SimChangedAt = transaction.SimChangedAt,
        BeneficiaryToken = transaction.BeneficiaryToken.Value,
        BeneficiaryIsMerchant = transaction.BeneficiaryIsMerchant,
        AgentId = transaction.AgentId,
        UssdSession = transaction.UssdSession,
        Timestamp = transaction.Timestamp,
        NotificationStatus = NotificationStatus.Pending.ToString(),
        ReceivedAt = DateTime.UtcNow
    };

    // ── Mapping TransactionRecord vers Transaction (Domain) ───────────────────

    private static Transaction ToDomain(TransactionRecord record) => new(
        transactionId: record.TransactionId,
        clientToken: new TokenHash(record.ClientToken),
        amount: new Money(record.Amount, record.Currency),
        channel: Enum.Parse<Channel>(record.Channel),
        zone: record.Zone,
        @operator: record.Operator,
        deviceId: new TokenHash(record.DeviceId),
        simChanged72h: record.SimChanged72h,
        simChangedAt: record.SimChangedAt,
        beneficiaryToken: new TokenHash(record.BeneficiaryToken),
        beneficiaryIsMerchant: record.BeneficiaryIsMerchant,
        agentId: record.AgentId,
        ussdSession: record.UssdSession,
        timestamp: record.Timestamp);
}