using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Infrastructure.Persistence;

/// <summary>
/// Implémentation de IPendingTransactionQueue avec PostgreSQL.
///
/// PATTERN "QUEUE VIA SKIP LOCKED" : DequeueAsync utilise une requête SQL brute
/// (WITH ... UPDATE ... RETURNING) plutôt que LINQ — EF Core ne génère pas
/// nativement FOR UPDATE SKIP LOCKED. C'est le seul repository de ce projet
/// qui contourne le LINQ standard, documenté explicitement ici et dans
/// PendingTransactionRecordConfiguration.cs.
///
/// SÛRETÉ CONCURRENTE : la requête est atomique (un seul aller-retour SQL) —
/// verrouille, filtre les lignes déjà prises par un autre pod (SKIP LOCKED),
/// et marque last_attempt_at, le tout en une seule transaction implicite.
/// Aucune coordination externe (pas de Redis lock, pas de leader election)
/// n'est nécessaire pour que plusieurs pods .NET consomment cette file
/// sans jamais traiter deux fois la même ligne.
///
/// FENÊTRE DE VISIBILITÉ : une ligne réclamée (last_attempt_at mis à jour)
/// redevient éligible après VisibilityTimeout si elle n'a pas été
/// Acknowledged ni Requeued — protège contre un pod qui crash après avoir
/// réclamé une ligne mais avant de la traiter.
/// </summary>
public sealed class PendingTransactionRepository : IPendingTransactionQueue
{
    /// <summary>
    /// Délai avant qu'une ligne réclamée mais non traitée redevienne éligible.
    /// Doit être significativement plus long que le temps de traitement normal
    /// d'un rescoring (appel FastAPI + mise à jour) pour éviter les doubles
    /// traitements en conditions normales.
    /// </summary>
    private const int VisibilityTimeoutSeconds = 30;

    /// <summary>
    /// Nombre maximal de tentatives avant qu'une transaction soit retirée
    /// de la file et signalée pour intervention manuelle plutôt que de
    /// tourner indéfiniment (payload corrompu, bug de désérialisation persistant).
    /// </summary>
    private const int MaxAttempts = 5;

    private readonly AppDbContext _dbContext;
    private readonly ILogger<PendingTransactionRepository> _logger;

    public PendingTransactionRepository(
        AppDbContext dbContext, ILogger<PendingTransactionRepository> logger)
    {
        _dbContext = dbContext;
        _logger = logger;
    }

    public async Task EnqueueAsync(
        Transaction transaction, CancellationToken cancellationToken = default)
    {
        // Idempotent — la contrainte unique sur TransactionId (voir
        // PendingTransactionRecordConfiguration) protège contre le doublon
        // même en cas de course entre deux appels concurrents.
        var exists = await _dbContext.PendingTransactions
            .AsNoTracking()
            .AnyAsync(p => p.TransactionId == transaction.TransactionId, cancellationToken);

        if (exists)
        {
            _logger.LogDebug(
                "Transaction {TransactionId} déjà en file de résilience — enqueue ignoré.",
                transaction.TransactionId);
            return;
        }

        var record = new PendingTransactionRecord
        {
            Id = Guid.NewGuid(),
            TransactionId = transaction.TransactionId,
            Operator = transaction.Operator,
            ClientToken = transaction.ClientToken.Value,
            Amount = transaction.Amount.Amount,
            Currency = transaction.Amount.Currency,
            Channel = transaction.Channel.ToString(),
            Zone = transaction.Zone,
            DeviceId = transaction.DeviceId.Value,
            SimChanged72h = transaction.SimChanged72h,
            SimChangedAt = transaction.SimChangedAt,
            BeneficiaryToken = transaction.BeneficiaryToken.Value,
            BeneficiaryIsMerchant = transaction.BeneficiaryIsMerchant,
            AgentId = transaction.AgentId,
            UssdSession = transaction.UssdSession,
            Timestamp = transaction.Timestamp,
            EnqueuedAt = DateTime.UtcNow,
            AttemptCount = 0,
            LastAttemptAt = null
        };

        _dbContext.PendingTransactions.Add(record);
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task<IReadOnlyList<Transaction>> DequeueAsync(
        int batchSize = 10, CancellationToken cancellationToken = default)
    {
        // Requête SQL brute — voir explication en tête de fichier.
        // FromSqlInterpolated protège contre l'injection SQL (paramètres liés).
        var records = await _dbContext.PendingTransactions
            .FromSqlInterpolated($@"
                WITH cte AS (
                    SELECT id FROM fraud_backend.pending_transactions
                    WHERE last_attempt_at IS NULL
                       OR last_attempt_at < now() - make_interval(secs => {VisibilityTimeoutSeconds})
                    ORDER BY enqueued_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT {batchSize}
                )
                UPDATE fraud_backend.pending_transactions pt
                SET last_attempt_at = now()
                FROM cte
                WHERE pt.id = cte.id
                RETURNING pt.*")
            .AsNoTracking()
            .ToListAsync(cancellationToken);

        if (records.Count > 0)
        {
            _logger.LogInformation(
                "Dépilé {Count} transaction(s) de la file de résilience.",
                records.Count);
        }

        return records.Select(ToDomain).ToList();
    }

    public async Task AcknowledgeAsync(
        string transactionId, CancellationToken cancellationToken = default)
    {
        // Rescoring réussi (vrai RiskScore reçu, pas un DefaultReview) —
        // suppression définitive de la file.
        var record = await _dbContext.PendingTransactions
            .FirstOrDefaultAsync(p => p.TransactionId == transactionId, cancellationToken);

        if (record is null)
        {
            _logger.LogWarning(
                "AcknowledgeAsync appelé pour {TransactionId} — introuvable en file. " +
                "Possible double-acknowledge ou timeout de visibilité dépassé.",
                transactionId);
            return;
        }

        _dbContext.PendingTransactions.Remove(record);
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task RequeueAsync(
        string transactionId, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.PendingTransactions
            .FirstOrDefaultAsync(p => p.TransactionId == transactionId, cancellationToken);

        if (record is null)
        {
            _logger.LogWarning(
                "RequeueAsync appelé pour {TransactionId} — introuvable en file.",
                transactionId);
            return;
        }

        record.AttemptCount++;

        if (record.AttemptCount >= MaxAttempts)
        {
            // Seuil dépassé — sortie de la file, intervention manuelle requise.
            // La ligne est supprimée plutôt que marquée "abandonnée" pour garder
            // le schéma simple ; le log Error est le point d'entrée pour
            // l'investigation (visible dans Grafana / agrégateur de logs).
            _logger.LogError(
                "Transaction {TransactionId} a dépassé le nombre maximal de tentatives " +
                "({MaxAttempts}) — retirée de la file de résilience. " +
                "Intervention manuelle requise : vérifier le payload et fraud-ml-service.",
                transactionId,
                MaxAttempts);

            _dbContext.PendingTransactions.Remove(record);
        }
        else
        {
            _logger.LogWarning(
                "Transaction {TransactionId} remise en file — tentative {AttemptCount}/{MaxAttempts}.",
                transactionId,
                record.AttemptCount,
                MaxAttempts);
        }

        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task<int> GetQueueSizeAsync(
        string operatorCode, CancellationToken cancellationToken = default)
    {
        return await _dbContext.PendingTransactions
            .AsNoTracking()
            .Where(p => p.Operator == operatorCode)
            .CountAsync(cancellationToken);
    }

    // ── Mapping PendingTransactionRecord vers Transaction (Domain) ────────────

    private static Transaction ToDomain(PendingTransactionRecord record) => new(
        transactionId: record.TransactionId,
        clientToken: new TokenHash(record.ClientToken),
        amount: new Money(record.Amount, record.Currency),
        channel: Enum.Parse<Domain.Enums.Channel>(record.Channel),
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