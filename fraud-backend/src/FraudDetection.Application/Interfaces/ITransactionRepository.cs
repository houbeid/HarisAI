using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Statut de notification retour vers l'opérateur après analyse.
/// .NET doit confirmer à Bankily/Sedad/Masrvi le résultat de la décision ML.
/// </summary>
public enum NotificationStatus
{
    /// <summary>Notification pas encore envoyée — état initial</summary>
    Pending,

    /// <summary>Opérateur notifié avec succès du résultat APPROVE/REVIEW/BLOCK</summary>
    Sent,

    /// <summary>Échec de notification — à retenter par PendingTransactionWorker</summary>
    Failed
}

/// <summary>
/// Port de persistance des transactions traitées côté .NET.
/// Stocké dans le schéma fraud_backend (PostgreSQL local au site).
///
/// PÉRIMÈTRE .NET — distinct de ml_audit (Python) :
///   ml_audit    → audit trail réglementaire BCM, immuable, géré par Python
///   fraud_backend → état opérationnel .NET : webhook reçu, décision ML,
///                   statut de notification retour vers l'opérateur
///
/// La question centrale à laquelle ce repository répond :
/// "A-t-on bien reçu ce webhook, obtenu une décision ML, et notifié l'opérateur ?"
/// </summary>
public interface ITransactionRepository
{
    /// <summary>
    /// Persiste une transaction après réception du webhook opérateur.
    /// Appelé dans AnalyzeTransactionHandler dès réception, avant l'appel ML —
    /// garantit une trace même si FastAPI est indisponible.
    /// </summary>
    Task SaveAsync(
        Transaction transaction,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Met à jour la transaction avec le résultat ML reçu de FastAPI.
    /// Appelé dans AnalyzeTransactionHandler après réception du RiskScore.
    /// </summary>
    Task UpdateScoreAsync(
        string transactionId,
        RiskScore score,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Met à jour le statut de notification retour vers l'opérateur.
    /// Appelé après tentative de notification — Sent si succès, Failed si échec.
    /// PendingTransactionWorker relit les Failed pour les retenter.
    /// </summary>
    Task UpdateNotificationStatusAsync(
        string transactionId,
        NotificationStatus status,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère une transaction par son identifiant.
    /// Retourne null si inconnue — cas normal pour un premier webhook.
    /// Retourner non-null signale un doublon potentiel (retry opérateur).
    /// </summary>
    Task<Transaction?> GetByIdAsync(
        string transactionId,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère l'historique des transactions d'un opérateur,
    /// triées par timestamp décroissant, avec pagination.
    /// Utilisé par GetTransactionHistoryHandler pour fraud-dashboard.
    /// decisionFilter null = toutes les décisions.
    /// </summary>
    Task<IReadOnlyList<Transaction>> GetHistoryAsync(
        string operatorCode,
        DecisionStatus? decisionFilter = null,
        int page = 1,
        int pageSize = 50,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Récupère les transactions dont la notification opérateur a échoué.
    /// Consommé exclusivement par PendingTransactionWorker pour retenter
    /// les notifications Failed dès que le service est de nouveau disponible.
    /// </summary>
    Task<IReadOnlyList<Transaction>> GetFailedNotificationsAsync(
        string operatorCode,
        CancellationToken cancellationToken = default);
}