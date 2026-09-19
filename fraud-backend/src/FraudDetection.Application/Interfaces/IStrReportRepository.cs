using FraudDetection.Application.Commands.GenerateStrReport;

namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Port de persistance des rapports STR (Suspicious Transaction Report).
/// Réutilise StrReportData (déjà défini dans GenerateStrReport/Command.cs)
/// comme représentation — pas de nouveau type Domain créé pour ça, un
/// rapport STR est un concept de reporting/conformité, pas une règle
/// métier du domaine central (Transaction, Alert).
///
/// L'implémentation concrète (StrReportRepository, Infrastructure) utilise
/// EF Core dans le schéma fraud_backend, comme les autres repositories.
/// </summary>
public interface IStrReportRepository
{
    /// <summary>
    /// Persiste un rapport STR généré. Appelé depuis GenerateStrReportHandler
    /// immédiatement après construction du StrReportData, avant toute
    /// tentative de transmission BCM (encore non implémentée).
    /// </summary>
    Task SaveAsync(StrReportData report, CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère un rapport par son ReportId (format STR-{OPERATOR}-{TIMESTAMP}-{HASH}).
    /// Retourne null si inconnu.
    /// </summary>
    Task<StrReportData?> GetByReportIdAsync(
        string reportId, CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère le rapport associé à une alerte donnée — utilisé pour
    /// l'idempotence : une alerte ne peut être confirmée qu'une seule fois
    /// (voir Alert.Confirm(), Domain), donc au plus un rapport STR par alerte.
    /// Retourne null si aucun rapport n'a encore été généré pour cette alerte.
    /// </summary>
    Task<StrReportData?> GetByAlertIdAsync(
        string alertId, CancellationToken cancellationToken = default);

    /// <summary>
    /// Historique des rapports STR d'un opérateur, triés par date de
    /// génération décroissante, avec pagination. Utilisé par
    /// GetStrReportsHandler pour alimenter ReportController.
    /// </summary>
    Task<IReadOnlyList<StrReportData>> GetHistoryAsync(
        string operatorCode,
        int page = 1,
        int pageSize = 50,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Compte le nombre total de rapports STR d'un opérateur, sans pagination.
    /// Utilisé pour exposer un total exploitable côté dashboard (pagination
    /// réelle plutôt que déduite du nombre d'éléments retournés sur la page
    /// courante) — absent avant cette version, réclamé par la session frontend.
    /// </summary>
    Task<int> CountAsync(
        string operatorCode, CancellationToken cancellationToken = default);
}