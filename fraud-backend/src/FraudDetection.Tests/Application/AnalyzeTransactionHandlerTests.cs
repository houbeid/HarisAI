using FraudDetection.Application.Commands.AnalyzeTransaction;
using FraudDetection.Application.Commands.CreateAlert;
using FraudDetection.Application.Exceptions;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.ValueObjects;
using MediatR;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace FraudDetection.Tests.Application;

public class AnalyzeTransactionHandlerTests
{
    // ── Mocks ────────────────────────────────────────────────────────────────
    private readonly Mock<IOperatorAdapterRegistry> _registryMock = new();
    private readonly Mock<IOperatorWebhookAdapter> _adapterMock = new();
    private readonly Mock<IMlScoringService> _mlServiceMock = new();
    private readonly Mock<ISimChangeService> _simChangeMock = new();
    private readonly Mock<ITransactionRepository> _transactionRepoMock = new();
    private readonly Mock<IPendingTransactionQueue> _pendingQueueMock = new();
    private readonly Mock<IMediator> _mediatorMock = new();

    private readonly AnalyzeTransactionHandler _handler;
    private readonly Transaction _validTransaction;
    private readonly RawWebhookPayload _validPayload;

    public AnalyzeTransactionHandlerTests()
    {
        _validTransaction = ApplicationTestFixtures.BuildTransaction();
        _validPayload = ApplicationTestFixtures.BuildPayload();

        // L'adaptateur individuel — utilisé indirectement via le registre
        _adapterMock
            .Setup(a => a.Adapt(It.IsAny<RawWebhookPayload>()))
            .Returns(_validTransaction);

        // Le registre résout systématiquement cet adaptateur pour le code opérateur valide
        _registryMock
            .Setup(r => r.Resolve(ApplicationTestFixtures.ValidOperatorCode))
            .Returns(_adapterMock.Object);

        // SimChangeService retourne la transaction inchangée par défaut
        _simChangeMock
            .Setup(s => s.EnrichAsync(It.IsAny<Transaction>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(_validTransaction);

        // Aucune transaction existante par défaut (pas de doublon)
        _transactionRepoMock
            .Setup(r => r.GetByIdAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((Transaction?)null);

        _handler = new AnalyzeTransactionHandler(
            adapterRegistry: _registryMock.Object,
            mlScoringService: _mlServiceMock.Object,
            simChangeService: _simChangeMock.Object,
            transactionRepository: _transactionRepoMock.Object,
            pendingQueue: _pendingQueueMock.Object,
            mediator: _mediatorMock.Object,
            logger: NullLogger<AnalyzeTransactionHandler>.Instance);
    }

    private AnalyzeTransactionCommand BuildCommand(RawWebhookPayload? payload = null) =>
        new(
            payload: payload ?? _validPayload,
            correlationId: ApplicationTestFixtures.ValidCorrelationId);

    // ── Tests du flux normal ──────────────────────────────────────────────────

    [Fact]
    public async Task Handle_ApproveDecision_ReturnsApproveResult()
    {
        var approveScore = ApplicationTestFixtures.BuildApproveScore();
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(approveScore);

        var result = await _handler.Handle(BuildCommand(), CancellationToken.None);

        Assert.Equal(ApplicationTestFixtures.ValidTransactionId, result.TransactionId);
        Assert.Equal(approveScore, result.Score);
        Assert.False(result.IsDefaultReview);
    }

    [Fact]
    public async Task Handle_ApproveDecision_DoesNotCreateAlert()
    {
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(ApplicationTestFixtures.BuildApproveScore());

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        // Aucune alerte créée pour APPROVE
        _mediatorMock.Verify(
            m => m.Send(It.IsAny<CreateAlertCommand>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task Handle_ReviewDecision_CreatesAlert()
    {
        var reviewScore = ApplicationTestFixtures.BuildReviewScore();
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(reviewScore);
        _mediatorMock
            .Setup(m => m.Send(It.IsAny<CreateAlertCommand>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CreateAlertResult(Guid.NewGuid()));

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        // Une alerte doit être créée pour REVIEW
        _mediatorMock.Verify(
            m => m.Send(
                It.Is<CreateAlertCommand>(c =>
                    c.AlertId == ApplicationTestFixtures.ValidAlertId &&
                    c.TransactionId == ApplicationTestFixtures.ValidTransactionId),
                It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task Handle_BlockDecision_CreatesAlert()
    {
        var blockScore = ApplicationTestFixtures.BuildBlockScore();
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(blockScore);
        _mediatorMock
            .Setup(m => m.Send(It.IsAny<CreateAlertCommand>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CreateAlertResult(Guid.NewGuid()));

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        _mediatorMock.Verify(
            m => m.Send(It.IsAny<CreateAlertCommand>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task Handle_AlwaysSavesTransactionBeforeMlCall()
    {
        // CRITIQUE : SaveAsync doit être appelé AVANT AnalyzeAsync
        // pour garantir une trace même si FastAPI crash après la sauvegarde.
        var saveOrder = new List<string>();

        _transactionRepoMock
            .Setup(r => r.SaveAsync(It.IsAny<Transaction>(), It.IsAny<CancellationToken>()))
            .Callback(() => saveOrder.Add("save"))
            .Returns(Task.CompletedTask);

        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .Callback(() => saveOrder.Add("ml"))
            .ReturnsAsync(ApplicationTestFixtures.BuildApproveScore());

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        Assert.Equal(new[] { "save", "ml" }, saveOrder);
    }

    // ── Tests de résilience (FastAPI indisponible) ────────────────────────────

    [Fact]
    public async Task Handle_MlServiceDown_ReturnsDefaultReview()
    {
        // Polly retourne DefaultReview quand FastAPI est indisponible
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(RiskScore.DefaultReview());

        var result = await _handler.Handle(BuildCommand(), CancellationToken.None);

        Assert.True(result.IsDefaultReview);
        Assert.Equal(50, result.Score.Score);
    }

    [Fact]
    public async Task Handle_MlServiceDown_EnqueuesForRetry()
    {
        // Quand FastAPI est down, la transaction doit être mise en file de rescoring
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(RiskScore.DefaultReview());

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        _pendingQueueMock.Verify(
            q => q.EnqueueAsync(It.IsAny<Transaction>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task Handle_MlServiceAvailable_NeverEnqueues()
    {
        // Quand FastAPI répond normalement, pas d'enqueue
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(ApplicationTestFixtures.BuildApproveScore());

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        _pendingQueueMock.Verify(
            q => q.EnqueueAsync(It.IsAny<Transaction>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    // ── Tests d'idempotence ───────────────────────────────────────────────────

    [Fact]
    public async Task Handle_DuplicateTransaction_SkipsSaveAsync()
    {
        // Retry opérateur — transaction déjà connue, on ne sauvegarde pas en double
        _transactionRepoMock
            .Setup(r => r.GetByIdAsync(
                ApplicationTestFixtures.ValidTransactionId,
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(_validTransaction);

        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(ApplicationTestFixtures.BuildApproveScore());

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        // SaveAsync ne doit pas être appelé pour une transaction existante
        _transactionRepoMock.Verify(
            r => r.SaveAsync(It.IsAny<Transaction>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    // ── Tests de validation métier ────────────────────────────────────────────

    [Fact]
    public async Task Handle_UnknownOperator_ThrowsOperatorNotConfiguredException()
    {
        var unknownPayload = ApplicationTestFixtures.BuildPayload(operatorCode: "UNKNOWN_OP");
        var command = new AnalyzeTransactionCommand(
            payload: unknownPayload,
            correlationId: ApplicationTestFixtures.ValidCorrelationId);

        // Le registre ne connaît pas "UNKNOWN_OP" — Resolve() retourne null par défaut (Moq)
        var exception = await Assert.ThrowsAsync<OperatorNotConfiguredException>(
            () => _handler.Handle(command, CancellationToken.None));

        Assert.Equal("UNKNOWN_OP", exception.OperatorCode);
    }

    [Fact]
    public async Task Handle_SimChangeServiceCalled_WithAdaptedTransaction()
    {
        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(It.IsAny<Transaction>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(ApplicationTestFixtures.BuildApproveScore());

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        // SimChangeService doit être appelé avec la transaction adaptée
        _simChangeMock.Verify(
            s => s.EnrichAsync(_validTransaction, It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task Handle_MlCalledWithEnrichedTransaction()
    {
        // Si SimChangeService enrichit la transaction (simChanged=true),
        // c'est la transaction enrichie qui doit être passée à FastAPI
        var enrichedTransaction = ApplicationTestFixtures.BuildTransaction(
            simChanged72h: true);

        _simChangeMock
            .Setup(s => s.EnrichAsync(_validTransaction, It.IsAny<CancellationToken>()))
            .ReturnsAsync(enrichedTransaction);

        _mlServiceMock
            .Setup(m => m.AnalyzeAsync(enrichedTransaction, It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(ApplicationTestFixtures.BuildApproveScore());

        await _handler.Handle(BuildCommand(), CancellationToken.None);

        // FastAPI reçoit la transaction enrichie, pas l'originale
        _mlServiceMock.Verify(
            m => m.AnalyzeAsync(enrichedTransaction, It.IsAny<string>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }
}