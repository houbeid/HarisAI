using FraudDetection.Application.Commands.CreateAlert;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Worker;
using MediatR;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace FraudDetection.Tests.Worker;

/// <summary>
/// Tests de PendingTransactionWorker via un vrai conteneur DI (mocks
/// enregistrés comme instances), en démarrant/arrêtant le vrai
/// BackgroundService (StartAsync/StopAsync) — pas de réflexion sur des
/// méthodes privées. Même esprit que les tests HmacAuthenticationHandler
/// (vrai pipeline plutôt que contournement).
///
/// Worker:PollIntervalSeconds configuré volontairement long (100s) pour
/// qu'un seul cycle s'exécute pendant la fenêtre du test — le premier
/// cycle démarre immédiatement dans ExecuteAsync, avant le premier délai.
/// </summary>
public sealed class PendingTransactionWorkerTests : IAsyncLifetime
{
    private readonly Mock<IMlScoringService> _mlServiceMock = new();
    private readonly Mock<IPendingTransactionQueue> _pendingQueueMock = new();
    private readonly Mock<ITransactionRepository> _transactionRepoMock = new();
    private readonly Mock<IMediator> _mediatorMock = new();

    private ServiceProvider _provider = null!;
    private PendingTransactionWorker _worker = null!;

    public Task InitializeAsync()
    {
        var services = new ServiceCollection();

        services.AddSingleton(_mlServiceMock.Object);
        services.AddSingleton(_pendingQueueMock.Object);
        services.AddSingleton(_transactionRepoMock.Object);
        services.AddSingleton(_mediatorMock.Object);

        _provider = services.BuildServiceProvider();

        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Operator:Code"] = "BANKILY",
                ["Worker:PollIntervalSeconds"] = "100",
                ["Worker:BatchSize"] = "10"
            })
            .Build();

        _worker = new PendingTransactionWorker(
            _provider.GetRequiredService<IServiceScopeFactory>(),
            configuration,
            NullLogger<PendingTransactionWorker>.Instance);

        // Healthy par défaut — chaque test ajuste ce qu'il faut.
        _mlServiceMock
            .Setup(m => m.IsHealthyAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);

        return Task.CompletedTask;
    }

    public async Task DisposeAsync()
    {
        await _provider.DisposeAsync();
    }

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

    /// <summary>Démarre le Worker, laisse un cycle s'exécuter, puis l'arrête proprement.</summary>
    private async Task RunOneCycleAsync()
    {
        await _worker.StartAsync(CancellationToken.None);
        await Task.Delay(300); // laisse le premier cycle (synchrone via mocks) se terminer
        await _worker.StopAsync(CancellationToken.None);
    }

    // ── Healthcheck avant dépilement ─────────────────────────────────────────

    [Fact]
    public async Task Worker_MlServiceUnhealthy_NeverDequeues()
    {
        _mlServiceMock
            .Setup(m => m.IsHealthyAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);

        await RunOneCycleAsync();

        _pendingQueueMock.Verify(
            q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task Worker_MlServiceHealthy_DoesDequeue()
    {
        _pendingQueueMock
            .Setup(q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(Array.Empty<Transaction>());

        await RunOneCycleAsync();

        _pendingQueueMock.Verify(
            q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()),
            Times.AtLeastOnce);
    }

    // ── File vide ────────────────────────────────────────────────────────────

    [Fact]
    public async Task Worker_EmptyQueue_NeverCallsAnalyzeAsync()
    {
        _pendingQueueMock
            .Setup(q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(Array.Empty<Transaction>());

        await RunOneCycleAsync();

        _mlServiceMock.Verify(
            m => m.AnalyzeAsync(
                It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    // ── Toujours DefaultReview — remise en file ────────────────────────────────

    [Fact]
    public async Task Worker_StillDefaultReview_RequeuesTransaction()
    {
        var transaction = BuildTransaction();
        _pendingQueueMock
            .Setup(q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new[] { transaction });
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(
                It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(RiskScore.DefaultReview());

        await RunOneCycleAsync();

        _pendingQueueMock.Verify(
            q => q.RequeueAsync(transaction.TransactionId, It.IsAny<CancellationToken>()),
            Times.AtLeastOnce);

        // Pas de mise à jour de score ni d'acquittement pour un échec persistant
        _transactionRepoMock.Verify(
            r => r.UpdateScoreAsync(
                It.IsAny<string>(), It.IsAny<RiskScore>(), It.IsAny<CancellationToken>()),
            Times.Never);
        _pendingQueueMock.Verify(
            q => q.AcknowledgeAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    // ── Rescoring réussi — APPROVE ───────────────────────────────────────────

    [Fact]
    public async Task Worker_SuccessfulApprove_UpdatesScoreAndAcknowledges()
    {
        var transaction = BuildTransaction();
        var approveScore = new RiskScore(score: 20, decision: DecisionStatus.Approve);

        _pendingQueueMock
            .Setup(q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new[] { transaction });
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(
                It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(approveScore);

        await RunOneCycleAsync();

        _transactionRepoMock.Verify(
            r => r.UpdateScoreAsync(
                transaction.TransactionId, approveScore, It.IsAny<CancellationToken>()),
            Times.AtLeastOnce);
        _pendingQueueMock.Verify(
            q => q.AcknowledgeAsync(transaction.TransactionId, It.IsAny<CancellationToken>()),
            Times.AtLeastOnce);

        // APPROVE ne déclenche jamais de création d'alerte
        _mediatorMock.Verify(
            m => m.Send(It.IsAny<CreateAlertCommand>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    // ── Rescoring réussi — REVIEW/BLOCK déclenche une alerte ────────────────────

    [Fact]
    public async Task Worker_SuccessfulReview_SendsCreateAlertCommand()
    {
        var transaction = BuildTransaction();
        var reviewScore = new RiskScore(
            score: 55, decision: DecisionStatus.Review,
            alertId: "ALT-C15FDD6C8FCB", fraudType: "STRUCTURING");

        _pendingQueueMock
            .Setup(q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new[] { transaction });
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(
                It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(reviewScore);

        await RunOneCycleAsync();

        _mediatorMock.Verify(
            m => m.Send(
                It.Is<CreateAlertCommand>(c =>
                    c.AlertId == "ALT-C15FDD6C8FCB" &&
                    c.TransactionId == transaction.TransactionId),
                It.IsAny<CancellationToken>()),
            Times.AtLeastOnce);
    }

    // ── Configuration incomplète ─────────────────────────────────────────────

    [Fact]
    public async Task Worker_MissingOperatorConfig_NeverProcesses()
    {
        var configWithoutOperator = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Worker:PollIntervalSeconds"] = "100"
                // Operator:Code intentionnellement absent
            })
            .Build();

        var worker = new PendingTransactionWorker(
            _provider.GetRequiredService<IServiceScopeFactory>(),
            configWithoutOperator,
            NullLogger<PendingTransactionWorker>.Instance);

        await worker.StartAsync(CancellationToken.None);
        await Task.Delay(300);
        await worker.StopAsync(CancellationToken.None);

        _pendingQueueMock.Verify(
            q => q.DequeueAsync(It.IsAny<int>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }
}