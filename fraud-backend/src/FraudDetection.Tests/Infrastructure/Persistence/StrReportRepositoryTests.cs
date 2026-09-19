using FraudDetection.Application.Commands.GenerateStrReport;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence;
using Xunit;

namespace FraudDetection.Tests.Infrastructure.Persistence;

/// <summary>
/// Premiers tests de StrReportRepository — aucun test n'existait jusqu'ici
/// pour ce repository. Couvre l'ensemble de la surface (pas seulement
/// CountAsync, ajouté pour le point 5 de la session frontend), cohérent
/// avec la discipline du skill : ne jamais laisser un composant partiellement
/// testé simplement parce qu'une seule méthode vient d'être modifiée.
/// </summary>
[Collection("PostgresCollection")]
public sealed class StrReportRepositoryTests : IAsyncLifetime
{
    private readonly PostgresFixture _fixture;
    private readonly StrReportRepository _repository;

    public StrReportRepositoryTests(PostgresFixture fixture)
    {
        _fixture = fixture;
        _repository = new StrReportRepository(fixture.DbContext);
    }

    public Task InitializeAsync() => _fixture.CleanupAsync();
    public Task DisposeAsync() => Task.CompletedTask;

    private static RiskScore BuildBlockScore(string alertId = "ALT-C15FDD6C8FCB") =>
        new(score: 87, decision: DecisionStatus.Block,
            alertId: alertId, fraudType: "SIM_SWAPPING",
            xgboostScore: 0.94, isolationScore: 0.85, tftScore: 0.88, gnnScore: 0.72);

    private static StrReportData BuildReport(
        string alertId = "ALT-C15FDD6C8FCB",
        string transactionId = "BNK-2024-001",
        string operatorCode = "BANKILY",
        DateTime? generatedAt = null) =>
        new(
            alertId: alertId,
            transactionId: transactionId,
            operatorCode: operatorCode,
            score: BuildBlockScore(alertId),
            confirmedBy: "agent@bankily.mr",
            agentNote: "Confirmé après vérification",
            generatedAt: generatedAt ?? DateTime.UtcNow);

    // ── Save / GetByReportId ─────────────────────────────────────────────────

    [Fact]
    public async Task SaveAsync_ThenGetByReportId_ReturnsReport()
    {
        var report = BuildReport();
        await _repository.SaveAsync(report, CancellationToken.None);

        var retrieved = await _repository.GetByReportIdAsync(
            report.ReportId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(report.ReportId, retrieved!.ReportId);
        Assert.Equal(report.AlertId, retrieved.AlertId);
        Assert.Equal(report.TransactionId, retrieved.TransactionId);
    }

    [Fact]
    public async Task GetByReportId_UnknownId_ReturnsNull()
    {
        var result = await _repository.GetByReportIdAsync(
            "STR-INEXISTANT", CancellationToken.None);

        Assert.Null(result);
    }

    [Fact]
    public async Task SaveAsync_PreservesAllScoreFields()
    {
        var report = BuildReport();
        await _repository.SaveAsync(report, CancellationToken.None);

        var retrieved = await _repository.GetByReportIdAsync(
            report.ReportId, CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(87, retrieved!.RiskScore);
        Assert.Equal("SIM_SWAPPING", retrieved.FraudType);
        Assert.Equal("BLOCK", retrieved.Decision);
        Assert.Equal(0.94, retrieved.XgboostScore);
        Assert.Equal("agent@bankily.mr", retrieved.ConfirmedBy);
        Assert.Equal("Confirmé après vérification", retrieved.AgentNote);
    }

    [Fact]
    public async Task SaveAsync_ReportIdPreservedExactly_NotRegeneratedOnReload()
    {
        // Vérifie le correctif du constructeur StrReportData(reportId: ...) —
        // la reconstruction depuis la base ne doit jamais générer un nouvel
        // identifiant, elle doit réutiliser exactement celui déjà stocké.
        var report = BuildReport();
        var originalReportId = report.ReportId;

        await _repository.SaveAsync(report, CancellationToken.None);
        var retrieved = await _repository.GetByReportIdAsync(
            originalReportId, CancellationToken.None);

        Assert.Equal(originalReportId, retrieved!.ReportId);
    }

    // ── GetByAlertId — idempotence ──────────────────────────────────────────

    [Fact]
    public async Task GetByAlertId_ExistingReport_ReturnsIt()
    {
        var report = BuildReport(alertId: "ALT-UNIQUE-001");
        await _repository.SaveAsync(report, CancellationToken.None);

        var retrieved = await _repository.GetByAlertIdAsync(
            "ALT-UNIQUE-001", CancellationToken.None);

        Assert.NotNull(retrieved);
        Assert.Equal(report.ReportId, retrieved!.ReportId);
    }

    [Fact]
    public async Task GetByAlertId_UnknownAlert_ReturnsNull()
    {
        var result = await _repository.GetByAlertIdAsync(
            "ALT-INEXISTANT", CancellationToken.None);

        Assert.Null(result);
    }

    // ── GetHistoryAsync — filtrage, tri, pagination ─────────────────────────

    [Fact]
    public async Task GetHistoryAsync_FiltersByOperator()
    {
        await _repository.SaveAsync(
            BuildReport(alertId: "ALT-BNK", transactionId: "BNK-001", operatorCode: "BANKILY"),
            CancellationToken.None);
        await _repository.SaveAsync(
            BuildReport(alertId: "ALT-SED", transactionId: "SED-001", operatorCode: "SEDAD"),
            CancellationToken.None);

        var bankilyHistory = await _repository.GetHistoryAsync(
            "BANKILY", cancellationToken: CancellationToken.None);

        Assert.Single(bankilyHistory);
        Assert.Equal("BANKILY", bankilyHistory[0].OperatorCode);
    }

    [Fact]
    public async Task GetHistoryAsync_OrdersByGeneratedAtDescending()
    {
        var older = BuildReport(
            alertId: "ALT-OLD", transactionId: "BNK-OLD",
            generatedAt: DateTime.UtcNow.AddHours(-2));
        var newer = BuildReport(
            alertId: "ALT-NEW", transactionId: "BNK-NEW",
            generatedAt: DateTime.UtcNow.AddHours(-1));

        await _repository.SaveAsync(older, CancellationToken.None);
        await _repository.SaveAsync(newer, CancellationToken.None);

        var history = await _repository.GetHistoryAsync(
            "BANKILY", cancellationToken: CancellationToken.None);

        Assert.Equal(2, history.Count);
        Assert.Equal("ALT-NEW", history[0].AlertId); // le plus récent en premier
    }

    [Fact]
    public async Task GetHistoryAsync_RespectsPagination()
    {
        for (int i = 0; i < 5; i++)
        {
            await _repository.SaveAsync(
                BuildReport(alertId: $"ALT-{i:D3}", transactionId: $"BNK-{i:D3}"),
                CancellationToken.None);
        }

        var page1 = await _repository.GetHistoryAsync(
            "BANKILY", page: 1, pageSize: 2, cancellationToken: CancellationToken.None);
        var page2 = await _repository.GetHistoryAsync(
            "BANKILY", page: 2, pageSize: 2, cancellationToken: CancellationToken.None);

        Assert.Equal(2, page1.Count);
        Assert.Equal(2, page2.Count);
        Assert.NotEqual(page1[0].AlertId, page2[0].AlertId);
    }

    // ── CountAsync — nouveau, réclamé par la session frontend (point 5) ────────

    [Fact]
    public async Task CountAsync_CountsAllReportsForOperator()
    {
        for (int i = 0; i < 3; i++)
        {
            await _repository.SaveAsync(
                BuildReport(alertId: $"ALT-{i:D3}", transactionId: $"BNK-{i:D3}"),
                CancellationToken.None);
        }

        var count = await _repository.CountAsync("BANKILY", CancellationToken.None);

        Assert.Equal(3, count);
    }

    [Fact]
    public async Task CountAsync_FiltersByOperator()
    {
        await _repository.SaveAsync(
            BuildReport(alertId: "ALT-BNK", transactionId: "BNK-001", operatorCode: "BANKILY"),
            CancellationToken.None);
        await _repository.SaveAsync(
            BuildReport(alertId: "ALT-SED", transactionId: "SED-001", operatorCode: "SEDAD"),
            CancellationToken.None);

        var bankilyCount = await _repository.CountAsync("BANKILY", CancellationToken.None);
        var sedadCount = await _repository.CountAsync("SEDAD", CancellationToken.None);

        Assert.Equal(1, bankilyCount);
        Assert.Equal(1, sedadCount);
    }

    [Fact]
    public async Task CountAsync_NoReports_ReturnsZero()
    {
        var count = await _repository.CountAsync("BANKILY", CancellationToken.None);

        Assert.Equal(0, count);
    }

    [Fact]
    public async Task CountAsync_IndependentOfPagination()
    {
        // Le total doit refléter TOUS les rapports, pas seulement ceux
        // d'une page — c'est exactement le point réclamé par le frontend :
        // pouvoir afficher "12 rapports au total" même si la page n'en
        // affiche que 5.
        for (int i = 0; i < 7; i++)
        {
            await _repository.SaveAsync(
                BuildReport(alertId: $"ALT-{i:D3}", transactionId: $"BNK-{i:D3}"),
                CancellationToken.None);
        }

        var page = await _repository.GetHistoryAsync(
            "BANKILY", page: 1, pageSize: 3, cancellationToken: CancellationToken.None);
        var total = await _repository.CountAsync("BANKILY", CancellationToken.None);

        Assert.Equal(3, page.Count);
        Assert.Equal(7, total);
    }
}