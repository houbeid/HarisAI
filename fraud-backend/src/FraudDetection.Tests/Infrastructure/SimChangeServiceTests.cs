using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.ExternalServices;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace FraudDetection.Tests.Infrastructure;

public class SimChangeServiceTests
{
    private readonly SimChangeService _service =
        new(NullLogger<SimChangeService>.Instance);

    private static Transaction BuildTransaction(
        bool simChanged72h,
        DateTime? simChangedAt,
        DateTime timestamp) =>
        new(
            transactionId: "BNK-2024-001",
            clientToken: new TokenHash("a3f9b2c1d4e5f6a7"),
            amount: new Money(47000m, "MRU"),
            channel: Channel.MobileApp,
            zone: "ROSSO",
            @operator: "BANKILY",
            deviceId: new TokenHash("device123hash456"),
            simChanged72h: simChanged72h,
            simChangedAt: simChangedAt,
            beneficiaryToken: new TokenHash("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: timestamp);

    // ── Cas 1 : SimChangedAt présent — recalcul depuis le timestamp ──────────

    [Fact]
    public async Task EnrichAsync_SimChangedWithin72h_RecalculatesToTrue()
    {
        var timestamp = new DateTime(2024, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var simChangedAt = timestamp.AddHours(-24); // 24h avant — dans la fenêtre 72h

        var transaction = BuildTransaction(
            simChanged72h: false, // valeur brute incorrecte envoyée par l'adaptateur
            simChangedAt: simChangedAt,
            timestamp: timestamp);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        Assert.True(result.SimChanged72h);
    }

    [Fact]
    public async Task EnrichAsync_SimChangedBeyond72h_RecalculatesToFalse()
    {
        var timestamp = new DateTime(2024, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var simChangedAt = timestamp.AddHours(-100); // 100h avant — hors fenêtre 72h

        var transaction = BuildTransaction(
            simChanged72h: true, // valeur brute incorrecte envoyée par l'adaptateur
            simChangedAt: simChangedAt,
            timestamp: timestamp);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        Assert.False(result.SimChanged72h);
    }

    [Fact]
    public async Task EnrichAsync_SimChangedExactly72h_IsWithinWindow()
    {
        // Limite exacte — doit être incluse (<=72h)
        var timestamp = new DateTime(2024, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var simChangedAt = timestamp.AddHours(-72);

        var transaction = BuildTransaction(
            simChanged72h: false,
            simChangedAt: simChangedAt,
            timestamp: timestamp);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        Assert.True(result.SimChanged72h);
    }

    [Fact]
    public async Task EnrichAsync_SimChangedJustOver72h_IsOutsideWindow()
    {
        var timestamp = new DateTime(2024, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var simChangedAt = timestamp.AddHours(-72).AddMinutes(-1);

        var transaction = BuildTransaction(
            simChanged72h: true,
            simChangedAt: simChangedAt,
            timestamp: timestamp);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        Assert.False(result.SimChanged72h);
    }

    [Fact]
    public async Task EnrichAsync_SimChangedAtInFuture_ReturnsFalse()
    {
        // Cas défensif : sim_changed_at postérieur au timestamp de la transaction
        // ne devrait jamais se produire en pratique, mais le calcul ne doit
        // pas planter ni retourner un résultat absurde (elapsed négatif).
        var timestamp = new DateTime(2024, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var simChangedAt = timestamp.AddHours(1); // après le timestamp — incohérent

        var transaction = BuildTransaction(
            simChanged72h: true,
            simChangedAt: simChangedAt,
            timestamp: timestamp);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        Assert.False(result.SimChanged72h);
    }

    [Fact]
    public async Task EnrichAsync_PreservesSimChangedAtValue()
    {
        var timestamp = new DateTime(2024, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var simChangedAt = timestamp.AddHours(-24);

        var transaction = BuildTransaction(
            simChanged72h: false,
            simChangedAt: simChangedAt,
            timestamp: timestamp);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        Assert.Equal(simChangedAt, result.SimChangedAt);
    }

    // ── Cas 2 : SimChangedAt absent — pas de source disponible ────────────────

    [Fact]
    public async Task EnrichAsync_NoSimChangedAt_ReturnsTransactionUnchanged()
    {
        var transaction = BuildTransaction(
            simChanged72h: false,
            simChangedAt: null, // aucune information disponible
            timestamp: DateTime.UtcNow);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        // Aucune modification possible sans source — valeur par défaut conservée
        Assert.False(result.SimChanged72h);
        Assert.Same(transaction, result); // même instance retournée, pas de recalcul
    }

    [Fact]
    public async Task EnrichAsync_NoSimChangedAt_DoesNotThrow()
    {
        var transaction = BuildTransaction(
            simChanged72h: false,
            simChangedAt: null,
            timestamp: DateTime.UtcNow);

        var exception = await Record.ExceptionAsync(
            () => _service.EnrichAsync(transaction, CancellationToken.None));

        Assert.Null(exception);
    }

    // ── Cohérence transaction préservée ────────────────────────────────────────

    [Fact]
    public async Task EnrichAsync_OtherFieldsRemainUnchanged()
    {
        var timestamp = new DateTime(2024, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var transaction = BuildTransaction(
            simChanged72h: false,
            simChangedAt: timestamp.AddHours(-24),
            timestamp: timestamp);

        var result = await _service.EnrichAsync(transaction, CancellationToken.None);

        Assert.Equal(transaction.TransactionId, result.TransactionId);
        Assert.Equal(transaction.ClientToken, result.ClientToken);
        Assert.Equal(transaction.Amount, result.Amount);
        Assert.Equal(transaction.Operator, result.Operator);
    }
}