using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence;
using Xunit;

namespace FraudDetection.Tests.Infrastructure.Persistence;

[Collection("PostgresCollection")]
public sealed class AlertRepositoryTests : IAsyncLifetime
{
    private readonly PostgresFixture _fixture;
    private readonly AlertRepository _repository;

    public AlertRepositoryTests(PostgresFixture fixture)
    {
        _fixture = fixture;
        _repository = new AlertRepository(fixture.DbContext);
    }

    public Task InitializeAsync() => _fixture.CleanupAsync();
    public Task DisposeAsync() => Task.CompletedTask;

    private static RiskScore BuildReviewScore() =>
        new(score: 55, decision: DecisionStatus.Review,
            alertId: "ALT-C15FDD6C8FCB", fraudType: "STRUCTURING");

    private static RiskScore BuildBlockScore() =>
        new(score: 87, decision: DecisionStatus.Block,
            alertId: "ALT-C15FDD6C8FCB", fraudType: "SIM_SWAPPING",
            xgboostScore: 0.94, isolationScore: 0.85, tftScore: 0.88, gnnScore: 0.72);

    private static Alert BuildAlert(
        RiskScore? score = null,
        string alertId = "ALT-C15FDD6C8FCB",
        string transactionId = "BNK-2024-001",
        string @operator = "BANKILY") =>
        new(
            alertId: alertId,
            transactionId: transactionId,
            @operator: @operator,
            score: score ?? BuildReviewScore(),
            createdAt: DateTime.UtcNow);

    // ── Save / GetByAlertId ──────────────────────────────────────────────────

    [Fact]
    public async Task SaveAsync_ThenGetByAlertId_ReturnsAlert()
    {
        var alert = BuildAlert();
        await _repository.SaveAsync(alert, CancellationToken.None);

        var retrieved = await _repository.GetByAlertIdAsync(alert.AlertId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(alert.AlertId, retrieved!.AlertId);
        Assert.Equal(alert.TransactionId, retrieved.TransactionId);
        Assert.Equal(AlertStatus.Pending, retrieved.Status);
    }

    [Fact]
    public async Task GetByAlertId_UnknownId_ReturnsNull()
    {
        var result = await _repository.GetByAlertIdAsync("ALT-INEXISTANT", CancellationToken.None);

        Assert.Null(result);
    }

    [Fact]
    public async Task SaveAsync_PreservesAllScoreFields()
    {
        var alert = BuildAlert(score: BuildBlockScore());
        await _repository.SaveAsync(alert, CancellationToken.None);

        var retrieved = await _repository.GetByAlertIdAsync(alert.AlertId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(87, retrieved!.Score.Score);
        Assert.Equal(DecisionStatus.Block, retrieved.Score.Decision);
        Assert.Equal("SIM_SWAPPING", retrieved.Score.FraudType);
        Assert.Equal(0.94, retrieved.Score.XgboostScore);
        Assert.Equal(0.85, retrieved.Score.IsolationScore);
    }

    // ── GetByTransactionId — idempotence ──────────────────────────────────────

    [Fact]
    public async Task GetByTransactionId_ExistingAlert_ReturnsIt()
    {
        var alert = BuildAlert(transactionId: "BNK-UNIQUE-001");
        await _repository.SaveAsync(alert, CancellationToken.None);

        var retrieved = await _repository.GetByTransactionIdAsync(
            "BNK-UNIQUE-001", CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(alert.AlertId, retrieved!.AlertId);
    }

    [Fact]
    public async Task GetByTransactionId_UnknownTransaction_ReturnsNull()
    {
        var result = await _repository.GetByTransactionIdAsync(
            "BNK-INEXISTANT", CancellationToken.None);

        Assert.Null(result);
    }

    // ── Update — cycle de vie Confirm/Dismiss ──────────────────────────────────

    [Fact]
    public async Task UpdateAsync_ConfirmedAlert_PersistsStatusChange()
    {
        var alert = BuildAlert();
        await _repository.SaveAsync(alert, CancellationToken.None);

        alert.Confirm("agent@bankily.mr", "SIM swap confirmé avec Mauritel");
        await _repository.UpdateAsync(alert, CancellationToken.None);

        var retrieved = await _repository.GetByAlertIdAsync(alert.AlertId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(AlertStatus.Confirmed, retrieved!.Status);
        Assert.Equal("agent@bankily.mr", retrieved.ReviewedBy);
        Assert.NotNull(retrieved.ReviewedAt);
        Assert.True(retrieved.RequiresStrReport);
    }

    [Fact]
    public async Task UpdateAsync_DismissedAlert_PersistsStatusChange()
    {
        var alert = BuildAlert();
        await _repository.SaveAsync(alert, CancellationToken.None);

        alert.Dismiss("agent@bankily.mr", "Faux positif");
        await _repository.UpdateAsync(alert, CancellationToken.None);

        var retrieved = await _repository.GetByAlertIdAsync(alert.AlertId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(AlertStatus.Dismissed, retrieved!.Status);
        Assert.False(retrieved.RequiresStrReport);
    }

    [Fact]
    public async Task UpdateAsync_UnknownAlert_ThrowsInvalidOperationException()
    {
        var alert = BuildAlert(alertId: "ALT-JAMAIS-SAUVEGARDE");

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => _repository.UpdateAsync(alert, CancellationToken.None));
    }

    // ── GetByStatusAsync — pagination et filtrage ──────────────────────────────

    [Fact]
    public async Task GetByStatusAsync_FiltersCorrectly()
    {
        var pendingAlert = BuildAlert(
            alertId: "ALT-PENDING-001", transactionId: "BNK-P-001");
        var confirmedAlert = BuildAlert(
            alertId: "ALT-CONFIRMED-001", transactionId: "BNK-C-001");

        await _repository.SaveAsync(pendingAlert, CancellationToken.None);
        await _repository.SaveAsync(confirmedAlert, CancellationToken.None);

        confirmedAlert.Confirm("agent@bankily.mr");
        await _repository.UpdateAsync(confirmedAlert, CancellationToken.None);

        var pendingResults = await _repository.GetByStatusAsync(
            AlertStatus.Pending, cancellationToken: CancellationToken.None);
        var confirmedResults = await _repository.GetByStatusAsync(
            AlertStatus.Confirmed, cancellationToken: CancellationToken.None);

        Assert.Single(pendingResults);
        Assert.Equal("ALT-PENDING-001", pendingResults[0].AlertId);

        Assert.Single(confirmedResults);
        Assert.Equal("ALT-CONFIRMED-001", confirmedResults[0].AlertId);
    }

    [Fact]
    public async Task GetByStatusAsync_FiltersByOperator()
    {
        var bankilyAlert = BuildAlert(
            alertId: "ALT-BNK-001", transactionId: "BNK-001", @operator: "BANKILY");
        var sedadAlert = BuildAlert(
            alertId: "ALT-SED-001", transactionId: "SED-001", @operator: "SEDAD");

        await _repository.SaveAsync(bankilyAlert, CancellationToken.None);
        await _repository.SaveAsync(sedadAlert, CancellationToken.None);

        var bankilyResults = await _repository.GetByStatusAsync(
            AlertStatus.Pending, operatorCode: "BANKILY", cancellationToken: CancellationToken.None);

        Assert.Single(bankilyResults);
        Assert.Equal("BANKILY", bankilyResults[0].Operator);
    }

    [Fact]
    public async Task GetByStatusAsync_OrdersByCreatedAtDescending()
    {
        var older = BuildAlert(alertId: "ALT-OLD", transactionId: "BNK-OLD");
        await _repository.SaveAsync(older, CancellationToken.None);
        await Task.Delay(50);

        var newer = BuildAlert(alertId: "ALT-NEW", transactionId: "BNK-NEW");
        await _repository.SaveAsync(newer, CancellationToken.None);

        var results = await _repository.GetByStatusAsync(
            AlertStatus.Pending, cancellationToken: CancellationToken.None);

        Assert.Equal(2, results.Count);
        Assert.Equal("ALT-NEW", results[0].AlertId); // le plus récent en premier
    }

    [Fact]
    public async Task GetByStatusAsync_RespectsPagination()
    {
        for (int i = 0; i < 5; i++)
        {
            await _repository.SaveAsync(
                BuildAlert(alertId: $"ALT-{i:D3}", transactionId: $"BNK-{i:D3}"),
                CancellationToken.None);
        }

        var page1 = await _repository.GetByStatusAsync(
            AlertStatus.Pending, page: 1, pageSize: 2, cancellationToken: CancellationToken.None);
        var page2 = await _repository.GetByStatusAsync(
            AlertStatus.Pending, page: 2, pageSize: 2, cancellationToken: CancellationToken.None);

        Assert.Equal(2, page1.Count);
        Assert.Equal(2, page2.Count);
        Assert.NotEqual(page1[0].AlertId, page2[0].AlertId);
    }

    // ── CountPendingAsync ────────────────────────────────────────────────────

    [Fact]
    public async Task CountPendingAsync_CountsOnlyPendingForOperator()
    {
        await _repository.SaveAsync(
            BuildAlert(alertId: "ALT-001", transactionId: "BNK-001", @operator: "BANKILY"),
            CancellationToken.None);
        await _repository.SaveAsync(
            BuildAlert(alertId: "ALT-002", transactionId: "BNK-002", @operator: "BANKILY"),
            CancellationToken.None);

        var confirmedAlert = BuildAlert(
            alertId: "ALT-003", transactionId: "BNK-003", @operator: "BANKILY");
        await _repository.SaveAsync(confirmedAlert, CancellationToken.None);
        confirmedAlert.Confirm("agent@bankily.mr");
        await _repository.UpdateAsync(confirmedAlert, CancellationToken.None);

        var count = await _repository.CountPendingAsync("BANKILY", CancellationToken.None);

        Assert.Equal(2, count); // seulement les 2 Pending, pas le Confirmed
    }
}