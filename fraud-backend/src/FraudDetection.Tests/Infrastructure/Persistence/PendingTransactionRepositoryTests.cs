using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace FraudDetection.Tests.Infrastructure.Persistence;

public sealed class PendingTransactionRepositoryTests : IClassFixture<PostgresFixture>, IAsyncLifetime
{
    private readonly PostgresFixture _fixture;
    private readonly PendingTransactionRepository _repository;

    public PendingTransactionRepositoryTests(PostgresFixture fixture)
    {
        _fixture = fixture;
        _repository = new PendingTransactionRepository(
            fixture.DbContext,
            NullLogger<PendingTransactionRepository>.Instance);
    }

    public Task InitializeAsync() => _fixture.CleanupAsync();
    public Task DisposeAsync() => Task.CompletedTask;

    private static Transaction BuildTransaction(string transactionId = "BNK-2024-001") =>
        new(
            transactionId: transactionId,
            clientToken: new TokenHash("a3f9b2c1d4e5f6a7"),
            amount: new Money(47000m, "MRU"),
            channel: Channel.MobileApp,
            zone: "ROSSO",
            @operator: "BANKILY",
            deviceId: new TokenHash("device123hash456"),
            simChanged72h: false,
            simChangedAt: null,
            beneficiaryToken: new TokenHash("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: DateTime.UtcNow);

    // ── Enqueue / Dequeue de base ──────────────────────────────────────────────

    [Fact]
    public async Task EnqueueAsync_ThenDequeue_ReturnsTransaction()
    {
        var transaction = BuildTransaction();
        await _repository.EnqueueAsync(transaction, CancellationToken.None);

        var dequeued = await _repository.DequeueAsync(batchSize: 10, CancellationToken.None);

        Assert.Single(dequeued);
        Assert.Equal(transaction.TransactionId, dequeued[0].TransactionId);
        Assert.Equal(transaction.Amount.Amount, dequeued[0].Amount.Amount);
    }

    [Fact]
    public async Task EnqueueAsync_Duplicate_DoesNotCreateSecondEntry()
    {
        var transaction = BuildTransaction();
        await _repository.EnqueueAsync(transaction, CancellationToken.None);
        await _repository.EnqueueAsync(transaction, CancellationToken.None); // doublon

        var size = await _repository.GetQueueSizeAsync("BANKILY", CancellationToken.None);

        Assert.Equal(1, size);
    }

    [Fact]
    public async Task DequeueAsync_EmptyQueue_ReturnsEmptyList()
    {
        var dequeued = await _repository.DequeueAsync(batchSize: 10, CancellationToken.None);

        Assert.Empty(dequeued);
    }

    [Fact]
    public async Task DequeueAsync_RespectsBatchSize()
    {
        for (int i = 0; i < 5; i++)
        {
            await _repository.EnqueueAsync(BuildTransaction($"BNK-2024-{i:D3}"), CancellationToken.None);
        }

        var dequeued = await _repository.DequeueAsync(batchSize: 3, CancellationToken.None);

        Assert.Equal(3, dequeued.Count);
    }

    [Fact]
    public async Task DequeueAsync_ReturnsOldestFirst()
    {
        // FIFO — enqueued_at croissant
        await _repository.EnqueueAsync(BuildTransaction("BNK-OLD"), CancellationToken.None);
        await Task.Delay(50); // garantit un enqueued_at strictement différent
        await _repository.EnqueueAsync(BuildTransaction("BNK-NEW"), CancellationToken.None);

        var dequeued = await _repository.DequeueAsync(batchSize: 1, CancellationToken.None);

        Assert.Single(dequeued);
        Assert.Equal("BNK-OLD", dequeued[0].TransactionId);
    }

    // ── SKIP LOCKED — le test le plus critique de tout le projet ───────────────

    [Fact]
    public async Task DequeueAsync_CalledConcurrently_NeverReturnsSameTransactionTwice()
    {
        // Simule N pods .NET dépilant simultanément — vérifie qu'aucune
        // transaction n'est jamais retournée par deux appels concurrents.
        // C'est LE test qui garantit la sûreté du mécanisme de résilience
        // documenté depuis le début de ce projet.
        const int transactionCount = 20;
        const int concurrentDequeuers = 4;

        for (int i = 0; i < transactionCount; i++)
        {
            await _repository.EnqueueAsync(
                BuildTransaction($"BNK-CONC-{i:D3}"), CancellationToken.None);
        }

        var connectionString = _fixture.DbContext.Database.GetConnectionString();

        // Chaque "pod" simulé a son propre DbContext — un DbContext n'est
        // pas thread-safe et ne doit jamais être partagé entre requêtes
        // concurrentes, exactement comme en production où chaque requête
        // HTTP a son propre DbContext scoped.
        var dequeueTasks = Enumerable.Range(0, concurrentDequeuers)
            .Select(async _ =>
            {
                var options = new DbContextOptionsBuilder<AppDbContext>()
                    .UseNpgsql(connectionString)
                    .UseSnakeCaseNamingConvention()
                    .Options;

                await using var scopedContext = new AppDbContext(options);
                var scopedRepository = new PendingTransactionRepository(
                    scopedContext, NullLogger<PendingTransactionRepository>.Instance);

                return await scopedRepository.DequeueAsync(batchSize: 10, CancellationToken.None);
            });

        var results = await Task.WhenAll(dequeueTasks);

        var allDequeuedIds = results.SelectMany(r => r.Select(t => t.TransactionId)).ToList();
        var uniqueIds = allDequeuedIds.Distinct().ToList();

        // Aucun doublon — chaque transaction n'a été dépilée qu'une seule fois
        Assert.Equal(allDequeuedIds.Count, uniqueIds.Count);

        // Toutes les transactions ont été dépilées au total (aucune perdue)
        Assert.Equal(transactionCount, allDequeuedIds.Count);
    }

    // ── Acknowledge ────────────────────────────────────────────────────────────

    [Fact]
    public async Task AcknowledgeAsync_RemovesFromQueue()
    {
        var transaction = BuildTransaction();
        await _repository.EnqueueAsync(transaction, CancellationToken.None);
        await _repository.DequeueAsync(batchSize: 10, CancellationToken.None);

        await _repository.AcknowledgeAsync(transaction.TransactionId, CancellationToken.None);

        var size = await _repository.GetQueueSizeAsync("BANKILY", CancellationToken.None);
        Assert.Equal(0, size);
    }

    [Fact]
    public async Task AcknowledgeAsync_UnknownTransactionId_DoesNotThrow()
    {
        var exception = await Record.ExceptionAsync(
            () => _repository.AcknowledgeAsync("BNK-INEXISTANT", CancellationToken.None));

        Assert.Null(exception);
    }

    // ── Requeue ──────────────────────────────────────────────────────────────

    [Fact]
    public async Task RequeueAsync_BelowMaxAttempts_StaysInQueue()
    {
        var transaction = BuildTransaction();
        await _repository.EnqueueAsync(transaction, CancellationToken.None);
        await _repository.DequeueAsync(batchSize: 10, CancellationToken.None);

        await _repository.RequeueAsync(transaction.TransactionId, CancellationToken.None);

        var size = await _repository.GetQueueSizeAsync("BANKILY", CancellationToken.None);
        Assert.Equal(1, size); // toujours présente — 1ère tentative < MaxAttempts (5)
    }

    [Fact]
    public async Task RequeueAsync_ExceedsMaxAttempts_RemovesFromQueue()
    {
        var transaction = BuildTransaction();
        await _repository.EnqueueAsync(transaction, CancellationToken.None);

        // MaxAttempts = 5 (constante interne du repository) — 5 requeue
        // successifs doivent sortir la transaction de la file.
        for (int i = 0; i < 5; i++)
        {
            await _repository.RequeueAsync(transaction.TransactionId, CancellationToken.None);
        }

        var size = await _repository.GetQueueSizeAsync("BANKILY", CancellationToken.None);
        Assert.Equal(0, size);
    }

    // ── Visibilité — fenêtre de 30 secondes ────────────────────────────────────

    [Fact]
    public async Task DequeueAsync_RecentlyClaimedTransaction_NotReturnedAgainImmediately()
    {
        var transaction = BuildTransaction();
        await _repository.EnqueueAsync(transaction, CancellationToken.None);

        var firstDequeue = await _repository.DequeueAsync(batchSize: 10, CancellationToken.None);
        Assert.Single(firstDequeue);

        // Immédiatement après — la ligne vient d'être marquée last_attempt_at,
        // elle ne doit pas être re-proposée avant l'expiration de la fenêtre
        // de visibilité (30 secondes).
        var secondDequeue = await _repository.DequeueAsync(batchSize: 10, CancellationToken.None);
        Assert.Empty(secondDequeue);
    }

    // ── GetQueueSizeAsync ────────────────────────────────────────────────────

    [Fact]
    public async Task GetQueueSizeAsync_FiltersByOperator()
    {
        await _repository.EnqueueAsync(BuildTransaction("BNK-001"), CancellationToken.None);

        var sedadTransaction = new Transaction(
            transactionId: "SED-001",
            clientToken: new TokenHash("a3f9b2c1d4e5f6a7"),
            amount: new Money(1000m, "MRU"),
            channel: Channel.MobileApp,
            zone: "NOUAKCHOTT",
            @operator: "SEDAD",
            deviceId: new TokenHash("device123hash456"),
            simChanged72h: false,
            simChangedAt: null,
            beneficiaryToken: new TokenHash("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: DateTime.UtcNow);
        await _repository.EnqueueAsync(sedadTransaction, CancellationToken.None);

        var bankilySize = await _repository.GetQueueSizeAsync("BANKILY", CancellationToken.None);
        var sedadSize = await _repository.GetQueueSizeAsync("SEDAD", CancellationToken.None);

        Assert.Equal(1, bankilySize);
        Assert.Equal(1, sedadSize);
    }
}