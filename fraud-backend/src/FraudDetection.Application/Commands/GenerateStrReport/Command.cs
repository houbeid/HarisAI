using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.ValueObjects;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Commands.GenerateStrReport;

/// <summary>
/// Commande MediatR déclenchée par ValidateAlertHandler quand un agent
/// de conformité confirme une fraude (Alert.Confirm()).
///
/// STR = Suspicious Transaction Report — rapport réglementaire obligatoire
/// envoyé à la BCM (Banque Centrale de Mauritanie) pour toute fraude confirmée.
///
/// POINT OUVERT — format exact BCM :
///   Le format de transmission STR à la BCM (API REST ? SFTP ? email chiffré ?)
///   n'est pas encore défini. IBcmReportingService est le port prévu pour
///   encapsuler ce mécanisme une fois obtenu via la réunion BCM.
///   En attendant, le rapport est généré et persisté localement — prêt à être
///   transmis dès que le canal de transmission BCM est connu.
/// </summary>
public sealed record GenerateStrReportCommand : IRequest<GenerateStrReportResult>
{
    public string AlertId { get; }
    public string TransactionId { get; }
    public string OperatorCode { get; }
    public RiskScore Score { get; }
    public string ConfirmedBy { get; }
    public string? Note { get; }
    public DateTime GeneratedAt { get; }

    public GenerateStrReportCommand(
        string alertId,
        string transactionId,
        string operatorCode,
        RiskScore score,
        string confirmedBy,
        string? note = null)
    {
        if (string.IsNullOrWhiteSpace(alertId))
            throw new ArgumentException("AlertId ne peut pas être vide.", nameof(alertId));

        if (string.IsNullOrWhiteSpace(transactionId))
            throw new ArgumentException("TransactionId ne peut pas être vide.", nameof(transactionId));

        if (string.IsNullOrWhiteSpace(operatorCode))
            throw new ArgumentException("OperatorCode ne peut pas être vide.", nameof(operatorCode));

        if (string.IsNullOrWhiteSpace(confirmedBy))
            throw new ArgumentException("ConfirmedBy ne peut pas être vide.", nameof(confirmedBy));

        ArgumentNullException.ThrowIfNull(score);

        AlertId = alertId.Trim();
        TransactionId = transactionId.Trim();
        OperatorCode = operatorCode.Trim().ToUpperInvariant();
        Score = score;
        ConfirmedBy = confirmedBy.Trim();
        Note = note?.Trim();
        GeneratedAt = DateTime.UtcNow;
    }
}

/// <summary>
/// Données structurées du rapport STR généré.
/// Représente ce qui sera transmis à la BCM une fois le canal défini.
/// </summary>
public sealed record StrReportData
{
    /// <summary>Identifiant unique du rapport — généré par .NET, pas par FastAPI</summary>
    public string ReportId { get; }

    public string AlertId { get; }
    public string TransactionId { get; }
    public string OperatorCode { get; }
    public string FraudType { get; }
    public int RiskScore { get; }
    public string Decision { get; }
    public string ConfirmedBy { get; }
    public string? AgentNote { get; }
    public DateTime GeneratedAt { get; }

    /// <summary>
    /// Scores individuels des quatre modèles ML — données techniques
    /// pour justifier la décision auprès de la BCM si demandé.
    /// </summary>
    public double? XgboostScore { get; }
    public double? IsolationScore { get; }
    public double? TftScore { get; }
    public double? GnnScore { get; }

    public StrReportData(
        string alertId,
        string transactionId,
        string operatorCode,
        RiskScore score,
        string confirmedBy,
        string? agentNote,
        DateTime generatedAt,
        string? reportId = null)
    {
        // reportId fourni = reconstruction depuis la persistance (StrReportRepository) —
        // on réutilise l'identifiant déjà stocké, on n'en génère jamais un nouveau.
        // reportId absent = création d'un nouveau rapport (GenerateStrReportHandler) —
        // génération d'un identifiant lisible basé sur generatedAt, pas DateTime.UtcNow,
        // pour que l'horodatage dans l'ID reflète toujours GeneratedAt de façon cohérente.
        ReportId = reportId
            ?? $"STR-{operatorCode}-{generatedAt:yyyyMMddHHmmss}-{Guid.NewGuid().ToString("N")[..8].ToUpperInvariant()}";
        AlertId = alertId;
        TransactionId = transactionId;
        OperatorCode = operatorCode;
        FraudType = score.FraudType ?? "UNKNOWN";
        RiskScore = score.Score;
        Decision = score.Decision.ToString().ToUpperInvariant();
        ConfirmedBy = confirmedBy;
        AgentNote = agentNote;
        GeneratedAt = generatedAt;
        XgboostScore = score.XgboostScore;
        IsolationScore = score.IsolationScore;
        TftScore = score.TftScore;
        GnnScore = score.GnnScore;
    }
}

/// <summary>Résultat retourné après génération du rapport.</summary>
public sealed record GenerateStrReportResult
{
    public string ReportId { get; }

    /// <summary>
    /// Vrai si le rapport a été transmis à la BCM.
    /// False tant que IBcmReportingService n'est pas implémenté —
    /// le rapport est persisté localement en attente de transmission.
    /// </summary>
    public bool Transmitted { get; }

    public GenerateStrReportResult(string reportId, bool transmitted = false)
    {
        ReportId = reportId;
        Transmitted = transmitted;
    }
}

/// <summary>
/// Handler de génération du rapport STR.
///
/// COMPORTEMENT ACTUEL (en attente du format BCM) :
///   Génère le rapport structuré, le persiste localement via
///   IStrReportRepository, et le logue avec niveau Warning — visible
///   dans Grafana et dans l'agrégateur de logs du site. La transmission
///   effective à la BCM sera ajoutée une fois IBcmReportingService implémenté.
///
/// POURQUOI NE PAS BLOQUER LE PIPELINE EN ATTENDANT LA BCM :
///   La chaîne Alert.Confirm() → GenerateStrReport → transmission BCM
///   est décomposée en trois responsabilités séparées précisément pour
///   que l'absence du canal de transmission BCM ne bloque pas la
///   capacité des agents à confirmer des fraudes en production.
/// </summary>
public sealed class GenerateStrReportHandler
    : IRequestHandler<GenerateStrReportCommand, GenerateStrReportResult>
{
    private readonly IStrReportRepository _strReportRepository;
    private readonly ILogger<GenerateStrReportHandler> _logger;

    // IBcmReportingService sera injecté ici une fois le format BCM connu.
    // private readonly IBcmReportingService _bcmReportingService;

    public GenerateStrReportHandler(
        IStrReportRepository strReportRepository,
        ILogger<GenerateStrReportHandler> logger)
    {
        _strReportRepository = strReportRepository;
        _logger = logger;
    }

    public async Task<GenerateStrReportResult> Handle(
        GenerateStrReportCommand request,
        CancellationToken cancellationToken)
    {
        // ── Idempotence — une alerte ne génère qu'un seul rapport STR ─────────
        // Alert.Confirm() (Domain) ne peut s'exécuter qu'une fois par alerte —
        // ce Handler ne devrait donc normalement être appelé qu'une seule fois
        // par AlertId. Cette vérification est un filet de sécurité supplémentaire
        // (ex: retry réseau côté ValidateAlertHandler) plutôt qu'un cas attendu.
        var existing = await _strReportRepository.GetByAlertIdAsync(
            request.AlertId, cancellationToken);

        if (existing is not null)
        {
            _logger.LogWarning(
                "Rapport STR déjà existant pour AlertId={AlertId} — " +
                "ReportId={ReportId}. Génération ignorée (idempotence).",
                request.AlertId, existing.ReportId);

            return new GenerateStrReportResult(existing.ReportId, transmitted: false);
        }

        // ── Construire le rapport STR ─────────────────────────────────────────
        var report = new StrReportData(
            alertId: request.AlertId,
            transactionId: request.TransactionId,
            operatorCode: request.OperatorCode,
            score: request.Score,
            confirmedBy: request.ConfirmedBy,
            agentNote: request.Note,
            generatedAt: request.GeneratedAt);

        // ── Persister le rapport ───────────────────────────────────────────────
        await _strReportRepository.SaveAsync(report, cancellationToken);

        // ── Logger le rapport (audit visible en attendant BCM) ─────────────────
        // Warning intentionnel — tout rapport STR doit être visible dans
        // Grafana et déclencher une notification aux superviseurs.
        _logger.LogWarning(
            "RAPPORT STR GÉNÉRÉ — ReportId={ReportId} AlertId={AlertId} " +
            "TransactionId={TransactionId} FraudType={FraudType} " +
            "RiskScore={RiskScore} Operator={Operator} ConfirmedBy={ConfirmedBy} " +
            "Note={Note} XgboostScore={XgboostScore}",
            report.ReportId,
            report.AlertId,
            report.TransactionId,
            report.FraudType,
            report.RiskScore,
            report.OperatorCode,
            report.ConfirmedBy,
            report.AgentNote ?? "aucune",
            report.XgboostScore);

        // ── Transmission BCM — à implémenter ─────────────────────────────────
        // bool transmitted = await _bcmReportingService.SubmitAsync(report, cancellationToken);
        // Pour l'instant : false — rapport persisté localement uniquement.
        const bool transmitted = false;

        if (!transmitted)
        {
            _logger.LogInformation(
                "Rapport STR {ReportId} généré et persisté localement — " +
                "transmission BCM en attente de IBcmReportingService.",
                report.ReportId);
        }

        return new GenerateStrReportResult(
            reportId: report.ReportId,
            transmitted: transmitted);
    }
}