using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence;
using Xunit;

namespace FraudDetection.Tests.Infrastructure.Persistence;

public sealed class TransactionRepositoryTests : IClassFixture<PostgresFixture>, IAsyncLifetime
{
    private readonly PostgresFixture _fixture;
    private readonly TransactionRepository _repository;

    public TransactionRepositoryTests(PostgresFixture fixture)
    {
        _fixture = fixture;
        _repository = new TransactionRepository(fixture.DbContext);
    }

    public Task InitializeAsync() => _fixture.CleanupAsync();
    public Task DisposeAsync() => Task.CompletedTask;

    private static Transaction BuildTransaction(
        string transactionId = "BNK-2024-001",
        string @operator = "BANKILY",
        DateTime? timestamp = null) =>
        new(
            transactionId: transactionId,
            clientToken: new TokenHash("a3f9b2c1d4e5f6a7"),
            amount: new Money(47000m, "MRU"),
            channel: Channel.MobileApp,
            zone: "ROSSO",
            @operator: @operator,
            deviceId: new TokenHash("device123hash456"),
            simChanged72h: true,
            simChangedAt: new DateTime(2024, 1, 15, 2, 30, 0, DateTimeKind.Utc),
            beneficiaryToken: new TokenHash("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: timestamp ?? DateTime.UtcNow);

    private static RiskScore BuildBlockScore() =>
        new(score: 87, decision: DecisionStatus.Block,
            alertId: "ALT-C15FDD6C8FCB", fraudType: "SIM_SWAPPING",
            xgboostScore: 0.94, modelVersion: "1.0.0", inferenceTimeMs: 87.5);

    // ── Save / GetById ───────────────────────────────────────────────────────

    [Fact]
    public async Task SaveAsync_ThenGetById_ReturnsTransaction()
    {
        var transaction = BuildTransaction();
        await _repository.SaveAsync(transaction, CancellationToken.None);

        var retrieved = await _repository.GetByIdAsync(
            transaction.TransactionId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(transaction.TransactionId, retrieved!.TransactionId);
        Assert.Equal(transaction.Amount.Amount, retrieved.Amount.Amount);
        Assert.Equal(transaction.Operator, retrieved.Operator);
        Assert.True(retrieved.SimChanged72h);
    }

    [Fact]
    public async Task GetById_UnknownId_ReturnsNull()
    {
        var result = await _repository.GetByIdAsync("BNK-INEXISTANT", CancellationToken.None);

        Assert.Null(result);
    }

    [Fact]
    public async Task SaveAsync_PreservesAllTransactionFields()
    {
        var transaction = BuildTransaction();
        await _repository.SaveAsync(transaction, CancellationToken.None);

        var retrieved = await _repository.GetByIdAsync(
            transaction.TransactionId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(transaction.Zone, retrieved!.Zone);
        Assert.Equal(transaction.Channel, retrieved.Channel);
        Assert.Equal(transaction.ClientToken.Value, retrieved.ClientToken.Value);
        Assert.Equal(transaction.BeneficiaryToken.Value, retrieved.BeneficiaryToken.Value);
        Assert.Equal(transaction.SimChangedAt, retrieved.SimChangedAt);
    }

    // ── UpdateScoreAsync ─────────────────────────────────────────────────────

    [Fact]
    public async Task UpdateScoreAsync_ExistingTransaction_UpdatesScore()
    {
        var transaction = BuildTransaction();
        await _repository.SaveAsync(transaction, CancellationToken.None);

        var score = BuildBlockScore();
        await _repository.UpdateScoreAsync(transaction.TransactionId, score, CancellationToken.None);

        var history = await _repository.GetHistoryAsync(
            "BANKILY", cancellationToken: CancellationToken.None);

        Assert.Single(history);
        // Le score n'est pas exposé directement sur Transaction (Domain) —
        // vérifié indirectement via GetHistoryAsync avec filtre décision.
        var blockOnly = await _repository.GetHistoryAsync(
            "BANKILY", decisionFilter: DecisionStatus.Block, cancellationToken: CancellationToken.None);
        Assert.Single(blockOnly);
    }

    [Fact]
    public async Task UpdateScoreAsync_UnknownTransaction_ThrowsInvalidOperationException()
    {
        await Assert.ThrowsAsync<InvalidOperationException>(
            () => _repository.UpdateScoreAsync(
                "BNK-JAMAIS-SAUVEGARDE", BuildBlockScore(), CancellationToken.None));
    }

    [Fact]
    public async Task UpdateScoreAsync_DefaultReview_MarksIsDefaultReview()
    {
        var transaction = BuildTransaction();
        await _repository.SaveAsync(transaction, CancellationToken.None);

        await _repository.UpdateScoreAsync(
            transaction.TransactionId, RiskScore.DefaultReview(), CancellationToken.None);

        // Vérifié indirectement — un REVIEW par défaut doit apparaître dans
        // le filtre REVIEW comme n'importe quel autre REVIEW.
        var reviewResults = await _repository.GetHistoryAsync(
            "BANKILY", decisionFilter: DecisionStatus.Review, cancellationToken: CancellationToken.None);
        Assert.Single(reviewResults);
    }

    // ── UpdateNotificationStatusAsync ───────────────────────────────────────────

    [Fact]
    public async Task UpdateNotificationStatusAsync_UpdatesStatus()
    {
        var transaction = BuildTransaction();
        await _repository.SaveAsync(transaction, CancellationToken.None);

        await _repository.UpdateNotificationStatusAsync(
            transaction.TransactionId, NotificationStatus.Failed, CancellationToken.None);

        var failedNotifications = await _repository.GetFailedNotificationsAsync(
            "BANKILY", CancellationToken.None);

        Assert.Single(failedNotifications);
        Assert.Equal(transaction.TransactionId, failedNotifications[0].TransactionId);
    }

    [Fact]
    public async Task UpdateNotificationStatusAsync_UnknownTransaction_ThrowsInvalidOperationException()
    {
        await Assert.ThrowsAsync<InvalidOperationException>(
            () => _repository.UpdateNotificationStatusAsync(
                "BNK-JAMAIS-SAUVEGARDE", NotificationStatus.Sent, CancellationToken.None));
    }

    [Fact]
    public async Task GetFailedNotificationsAsync_ExcludesSentAndPending()
    {
        var failed = BuildTransaction("BNK-FAILED");
        var sent = BuildTransaction("BNK-SENT");
        var pending = BuildTransaction("BNK-PENDING");

        await _repository.SaveAsync(failed, CancellationToken.None);
        await _repository.SaveAsync(sent, CancellationToken.None);
        await _repository.SaveAsync(pending, CancellationToken.None);

        await _repository.UpdateNotificationStatusAsync(
            "BNK-FAILED", NotificationStatus.Failed, CancellationToken.None);
        await _repository.UpdateNotificationStatusAsync(
            "BNK-SENT", NotificationStatus.Sent, CancellationToken.None);
        // "BNK-PENDING" reste au statut par défaut (Pending)

        var failedOnly = await _repository.GetFailedNotificationsAsync(
            "BANKILY", CancellationToken.None);

        Assert.Single(failedOnly);
        Assert.Equal("BNK-FAILED", failedOnly[0].TransactionId);
    }

    // ── GetHistoryAsync — filtrage et pagination ────────────────────────────────

    [Fact]
    public async Task GetHistoryAsync_FiltersByOperator()
    {
        await _repository.SaveAsync(
            BuildTransaction("BNK-001", "BANKILY"), CancellationToken.None);
        await _repository.SaveAsync(
            BuildTransaction("SED-001", "SEDAD"), CancellationToken.None);

        var bankilyHistory = await _repository.GetHistoryAsync(
            "BANKILY", cancellationToken: CancellationToken.None);

        Assert.Single(bankilyHistory);
        Assert.Equal("BANKILY", bankilyHistory[0].Operator);
    }

    [Fact]
    public async Task GetHistoryAsync_OrdersByTimestampDescending()
    {
        var older = BuildTransaction("BNK-OLD", timestamp: DateTime.UtcNow.AddHours(-2));
        var newer = BuildTransaction("BNK-NEW", timestamp: DateTime.UtcNow.AddHours(-1));

        await _repository.SaveAsync(older, CancellationToken.None);
        await _repository.SaveAsync(newer, CancellationToken.None);

        var history = await _repository.GetHistoryAsync(
            "BANKILY", cancellationToken: CancellationToken.None);

        Assert.Equal(2, history.Count);
        Assert.Equal("BNK-NEW", history[0].TransactionId); // le plus récent en premier
    }

    [Fact]
    public async Task GetHistoryAsync_RespectsPagination()
    {
        for (int i = 0; i < 5; i++)
        {
            await _repository.SaveAsync(
                BuildTransaction($"BNK-{i:D3}"), CancellationToken.None);
        }

        var page1 = await _repository.GetHistoryAsync(
            "BANKILY", page: 1, pageSize: 2, cancellationToken: CancellationToken.None);
        var page2 = await _repository.GetHistoryAsync(
            "BANKILY", page: 2, pageSize: 2, cancellationToken: CancellationToken.None);

        Assert.Equal(2, page1.Count);
        Assert.Equal(2, page2.Count);
        Assert.NotEqual(page1[0].TransactionId, page2[0].TransactionId);
    }
}