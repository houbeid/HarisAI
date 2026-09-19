using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;

namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Port de persistance des alertes générées pour les décisions REVIEW et BLOCK.
/// L'implémentation concrète (AlertRepository.cs, Infrastructure) utilise
/// EF Core dans le schéma fraud_backend de PostgreSQL local au site.
///
/// PÉRIMÈTRE : uniquement les alertes côté .NET — l'audit trail complet
/// (toutes les décisions APPROVE/REVIEW/BLOCK) est géré par PostgresAuditStore
/// côté Python dans le schéma ml_audit. Ces deux stores ne se dupliquent pas :
/// ml_audit = source de vérité réglementaire BCM
/// fraud_backend = état de traitement par les agents de conformité
/// </summary>
public interface IAlertRepository
{
    /// <summary>
    /// Persiste une nouvelle alerte.
    /// Appelé depuis CreateAlertHandler après détection d'une décision REVIEW ou BLOCK.
    /// </summary>
    Task SaveAsync(Alert alert, CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère une alerte par son AlertId FastAPI (format ALT-XXXXXXXXXXXXXXXX).
    /// Retourne null si l'alerte n'existe pas dans la base locale .NET.
    /// Utilisé par ValidateAlertHandler (Confirm/Dismiss) et GenerateStrReportHandler.
    /// </summary>
    Task<Alert?> GetByAlertIdAsync(string alertId, CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère une alerte par le TransactionId qu'elle couvre.
    /// Retourne null si aucune alerte n'existe pour cette transaction.
    /// Utilisé pour vérifier l'idempotence — évite de créer deux alertes
    /// pour la même transaction en cas de retry du webhook opérateur.
    /// </summary>
    Task<Alert?> GetByTransactionIdAsync(string transactionId, CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère les alertes correspondant à un ou plusieurs statuts, triées par
    /// date de création décroissante. Utilisé par GetAlertsHandler pour alimenter
    /// fraud-dashboard (agents de conformité).
    ///
    /// PLUSIEURS STATUTS EN UN SEUL APPEL — permet un filtre "Traitées" combinant
    /// Confirmed ET Dismissed sans devoir faire deux requêtes séparées côté
    /// dashboard puis fusionner côté client. statuses vide ou null = tous les statuts.
    /// operatorCode null = toutes les alertes du site (cas superviseur).
    /// </summary>
    Task<IReadOnlyList<Alert>> GetByStatusAsync(
        IReadOnlyCollection<AlertStatus>? statuses,
        string? operatorCode = null,
        int page = 1,
        int pageSize = 50,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Compte les alertes correspondant à un ou plusieurs statuts, sans pagination.
    /// Utilisé pour exposer un total exploitable côté dashboard (ex: badge
    /// "X alertes traitées"), là où CountPendingAsync ne couvrait que Pending.
    /// statuses vide ou null = tous les statuts.
    /// </summary>
    Task<int> CountByStatusesAsync(
        IReadOnlyCollection<AlertStatus>? statuses,
        string? operatorCode = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Met à jour une alerte après Confirm() ou Dismiss() par un agent de conformité.
    /// Lève une exception si l'alerte n'existe pas — signale un bug de cohérence,
    /// pas un cas métier normal.
    /// </summary>
    Task UpdateAsync(Alert alert, CancellationToken cancellationToken = default);

    /// <summary>
    /// Compte les alertes Pending par opérateur.
    /// Utilisé par MetricsCollector pour exposer une jauge Prometheus —
    /// indicateur clé pour détecter un backlog anormal chez un agent de conformité.
    /// </summary>
    Task<int> CountPendingAsync(string operatorCode, CancellationToken cancellationToken = default);
}