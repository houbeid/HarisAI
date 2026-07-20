using FraudDetection.Application.Commands.CreateAlert;
using FraudDetection.Application.Commands.GenerateStrReport;
using FraudDetection.Application.Commands.ValidateAlert;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using MediatR;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace FraudDetection.Tests.Application;

// ═══════════════════════════════════════════════════════════
// CREATE ALERT HANDLER
// ═══════════════════════════════════════════════════════════

public class CreateAlertHandlerTests
{
    private readonly Mock<IAlertRepository> _alertRepoMock = new();
    private readonly CreateAlertHandler _handler;

    public CreateAlertHandlerTests()
    {
        _handler = new CreateAlertHandler(
            alertRepository: _alertRepoMock.Object,
            logger: NullLogger<CreateAlertHandler>.Instance);
    }

    [Fact]
    public async Task Handle_NewAlert_SavesAndReturnsNewId()
    {
        // Aucune alerte existante pour cette transaction
        _alertRepoMock
            .Setup(r => r.GetByTransactionIdAsync(
                ApplicationTestFixtures.ValidTransactionId,
                It.IsAny<CancellationToken>()))
            .ReturnsAsync((Alert?)null);

        var command = new CreateAlertCommand(
            alertId: ApplicationTestFixtures.ValidAlertId,
            transactionId: ApplicationTestFixtures.ValidTransactionId,
            operatorCode: ApplicationTestFixtures.ValidOperatorCode,
            score: ApplicationTestFixtures.BuildReviewScore());

        var result = await _handler.Handle(command, CancellationToken.None);

        Assert.False(result.AlreadyExisted);
        Assert.NotEqual(Guid.Empty, result.AlertLocalId);

        // SaveAsync doit avoir été appelé une fois
        _alertRepoMock.Verify(
            r => r.SaveAsync(It.IsAny<Alert>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task Handle_DuplicateTransaction_ReturnsAlreadyExisted()
    {
        // Alerte déjà existante — retry opérateur
        var existingAlert = ApplicationTestFixtures.BuildAlert();
        _alertRepoMock
            .Setup(r => r.GetByTransactionIdAsync(
                ApplicationTestFixtures.ValidTransactionId,
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(existingAlert);

        var command = new CreateAlertCommand(
            alertId: ApplicationTestFixtures.ValidAlertId,
            transactionId: ApplicationTestFixtures.ValidTransactionId,
            operatorCode: ApplicationTestFixtures.ValidOperatorCode,
            score: ApplicationTestFixtures.BuildReviewScore());

        var result = await _handler.Handle(command, CancellationToken.None);

        Assert.True(result.AlreadyExisted);
        Assert.Equal(existingAlert.Id, result.AlertLocalId);

        // SaveAsync ne doit PAS être appelé — idempotence
        _alertRepoMock.Verify(
            r => r.SaveAsync(It.IsAny<Alert>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public void Command_ApproveScore_ThrowsArgumentException()
    {
        // CreateAlertCommand ne peut pas être créé pour APPROVE
        Assert.Throws<ArgumentException>(() => new CreateAlertCommand(
            alertId: ApplicationTestFixtures.ValidAlertId,
            transactionId: ApplicationTestFixtures.ValidTransactionId,
            operatorCode: ApplicationTestFixtures.ValidOperatorCode,
            score: ApplicationTestFixtures.BuildApproveScore()));
    }
}

// ═══════════════════════════════════════════════════════════
// VALIDATE ALERT HANDLER
// ═══════════════════════════════════════════════════════════

public class ValidateAlertHandlerTests
{
    private readonly Mock<IAlertRepository> _alertRepoMock = new();
    private readonly Mock<IMediator> _mediatorMock = new();
    private readonly ValidateAlertHandler _handler;

    public ValidateAlertHandlerTests()
    {
        _handler = new ValidateAlertHandler(
            alertRepository: _alertRepoMock.Object,
            mediator: _mediatorMock.Object,
            logger: NullLogger<ValidateAlertHandler>.Instance);
    }

    [Fact]
    public async Task Handle_Confirm_ChangesStatusAndTriggersStrReport()
    {
        var alert = ApplicationTestFixtures.BuildAlert();
        _alertRepoMock
            .Setup(r => r.GetByAlertIdAsync(
                ApplicationTestFixtures.ValidAlertId,
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(alert);
        _mediatorMock
            .Setup(m => m.Send(
                It.IsAny<GenerateStrReportCommand>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GenerateStrReportResult("STR-BANKILY-001"));

        var command = new ValidateAlertCommand(
            alertId: ApplicationTestFixtures.ValidAlertId,
            action: AlertValidationAction.Confirm,
            reviewedBy: ApplicationTestFixtures.ValidReviewedBy,
            note: "SIM swap confirmé avec Mauritel");

        var result = await _handler.Handle(command, CancellationToken.None);

        Assert.Equal(AlertValidationAction.Confirm, result.ActionApplied);
        Assert.True(result.StrReportTriggered);

        // UpdateAsync doit être appelé avec l'alerte Confirmed
        _alertRepoMock.Verify(
            r => r.UpdateAsync(
                It.Is<Alert>(a => a.Status == FraudDetection.Domain.Enums.AlertStatus.Confirmed),
                It.IsAny<CancellationToken>()),
            Times.Once);

        // STR déclenché via MediatR
        _mediatorMock.Verify(
            m => m.Send(It.IsAny<GenerateStrReportCommand>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task Handle_Dismiss_ChangesStatusWithoutStrReport()
    {
        var alert = ApplicationTestFixtures.BuildAlert();
        _alertRepoMock
            .Setup(r => r.GetByAlertIdAsync(
                ApplicationTestFixtures.ValidAlertId,
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(alert);

        var command = new ValidateAlertCommand(
            alertId: ApplicationTestFixtures.ValidAlertId,
            action: AlertValidationAction.Dismiss,
            reviewedBy: ApplicationTestFixtures.ValidReviewedBy,
            note: "Faux positif — déplacement habituel du client");

        var result = await _handler.Handle(command, CancellationToken.None);

        Assert.Equal(AlertValidationAction.Dismiss, result.ActionApplied);
        Assert.False(result.StrReportTriggered);

        // Aucun rapport STR pour un Dismiss
        _mediatorMock.Verify(
            m => m.Send(It.IsAny<GenerateStrReportCommand>(), It.IsAny<CancellationToken>()),
            Times.Never);

        // UpdateAsync appelé avec alerte Dismissed
        _alertRepoMock.Verify(
            r => r.UpdateAsync(
                It.Is<Alert>(a => a.Status == FraudDetection.Domain.Enums.AlertStatus.Dismissed),
                It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task Handle_AlertNotFound_ThrowsInvalidOperationException()
    {
        _alertRepoMock
            .Setup(r => r.GetByAlertIdAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((Alert?)null);

        var command = new ValidateAlertCommand(
            alertId: "ALT-INEXISTANT",
            action: AlertValidationAction.Confirm,
            reviewedBy: ApplicationTestFixtures.ValidReviewedBy);

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => _handler.Handle(command, CancellationToken.None));
    }

    [Fact]
    public async Task Handle_AlreadyConfirmed_ThrowsInvalidOperationException()
    {
        // Une alerte déjà traitée ne peut plus être modifiée
        // — règle métier imposée par Alert.Confirm() dans le Domain
        var alert = ApplicationTestFixtures.BuildAlert();
        alert.Confirm(ApplicationTestFixtures.ValidReviewedBy);

        _alertRepoMock
            .Setup(r => r.GetByAlertIdAsync(
                ApplicationTestFixtures.ValidAlertId,
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(alert);

        var command = new ValidateAlertCommand(
            alertId: ApplicationTestFixtures.ValidAlertId,
            action: AlertValidationAction.Confirm,
            reviewedBy: "autre.agent@bankily.mr");

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => _handler.Handle(command, CancellationToken.None));
    }
}