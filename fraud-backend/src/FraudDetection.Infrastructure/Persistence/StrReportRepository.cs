using FraudDetection.Application.Commands.GenerateStrReport;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;

namespace FraudDetection.Infrastructure.Persistence;

/// <summary>
/// Implémentation de IStrReportRepository avec EF Core / PostgreSQL.
/// Responsable du mapping bidirectionnel StrReportData (Application) vers
/// StrReportRecord (persistance) — même principe que les autres repositories,
/// même si StrReportData n'est pas une entité du Domain mais un modèle
/// applicatif (voir IStrReportRepository pour le raisonnement).
/// </summary>
public sealed class StrReportRepository : IStrReportRepository
{
    private readonly AppDbContext _dbContext;

    public StrReportRepository(AppDbContext dbContext)
    {
        _dbContext = dbContext;
    }

    public async Task SaveAsync(StrReportData report, CancellationToken cancellationToken = default)
    {
        var record = ToRecord(report);
        _dbContext.StrReports.Add(record);
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task<StrReportData?> GetByReportIdAsync(
        string reportId, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.StrReports
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.ReportId == reportId, cancellationToken);

        return record is null ? null : ToStrReportData(record);
    }

    public async Task<StrReportData?> GetByAlertIdAsync(
        string alertId, CancellationToken cancellationToken = default)
    {
        var record = await _dbContext.StrReports
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.AlertId == alertId, cancellationToken);

        return record is null ? null : ToStrReportData(record);
    }

    public async Task<IReadOnlyList<StrReportData>> GetHistoryAsync(
        string operatorCode,
        int page = 1,
        int pageSize = 50,
        CancellationToken cancellationToken = default)
    {
        var records = await _dbContext.StrReports
            .AsNoTracking()
            .Where(r => r.Operator == operatorCode)
            .OrderByDescending(r => r.GeneratedAt)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync(cancellationToken);

        return records.Select(ToStrReportData).ToList();
    }

    public async Task<int> CountAsync(
        string operatorCode, CancellationToken cancellationToken = default)
    {
        return await _dbContext.StrReports
            .AsNoTracking()
            .Where(r => r.Operator == operatorCode)
            .CountAsync(cancellationToken);
    }

    // ── Mapping StrReportData (Application) vers StrReportRecord ──────────────

    private static StrReportRecord ToRecord(StrReportData report) => new()
    {
        ReportId = report.ReportId,
        AlertId = report.AlertId,
        TransactionId = report.TransactionId,
        Operator = report.OperatorCode,
        FraudType = report.FraudType,
        RiskScore = report.RiskScore,
        Decision = report.Decision,
        ConfirmedBy = report.ConfirmedBy,
        AgentNote = report.AgentNote,
        GeneratedAt = report.GeneratedAt,
        XgboostScore = report.XgboostScore,
        IsolationScore = report.IsolationScore,
        TftScore = report.TftScore,
        GnnScore = report.GnnScore,
        // Toujours false à la création — reflète honnêtement l'absence
        // actuelle de IBcmReportingService (voir GenerateStrReportHandler).
        Transmitted = false,
        TransmittedAt = null
    };

    // ── Mapping StrReportRecord vers StrReportData (Application) ──────────────

    private static StrReportData ToStrReportData(StrReportRecord record)
    {
        // Reconstruction du RiskScore minimal nécessaire au constructeur de
        // StrReportData — les champs non stockés directement dans StrReportRecord
        // ne sont pas recréés à l'identique de l'original FastAPI, seulement
        // ce qui est nécessaire pour représenter fidèlement le rapport déjà généré.
        // ignoreCase: true — StrReportData.Decision est stocké en MAJUSCULES
        // (.ToUpperInvariant() dans son constructeur), mais l'enum DecisionStatus
        // utilise le PascalCase standard C# (Block, pas BLOCK). Sans ignoreCase,
        // Enum.Parse échoue systématiquement à la relecture — bug réel détecté
        // uniquement une fois StrReportRepositoryTests.cs écrit, ce repository
        // n'ayant auparavant aucun test.
        var decision = Enum.Parse<DecisionStatus>(record.Decision, ignoreCase: true);
        var score = new RiskScore(
            score: record.RiskScore,
            decision: decision,
            fraudType: record.FraudType,
            alertId: record.AlertId,
            xgboostScore: record.XgboostScore,
            isolationScore: record.IsolationScore,
            tftScore: record.TftScore,
            gnnScore: record.GnnScore);

        return new StrReportData(
            alertId: record.AlertId,
            transactionId: record.TransactionId,
            operatorCode: record.Operator,
            score: score,
            confirmedBy: record.ConfirmedBy,
            agentNote: record.AgentNote,
            generatedAt: record.GeneratedAt,
            reportId: record.ReportId); // réutilise l'ID déjà stocké, n'en génère pas un nouveau
    }
}