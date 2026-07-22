namespace FraudDetection.Infrastructure.Persistence.Records;

/// <summary>
/// Modèle de persistance EF Core pour la file de résilience locale.
/// Une ligne = une transaction en attente de rescoring parce que
/// fraud-ml-service était indisponible au moment de la réception du webhook.
///
/// CONSOMMATION CONCURRENTE SÛRE : PendingTransactionRepository utilise
/// SELECT ... FOR UPDATE SKIP LOCKED sur cette table pour garantir qu'avec
/// plusieurs pods .NET actifs simultanément, chaque ligne n'est traitée
/// que par un seul pod à la fois — sans coordination externe (pas de Redis
/// lock, pas de leader election).
///
/// Toutes les données nécessaires pour reconstruire une Transaction complète
/// (Domain) sont dupliquées ici plutôt que de référencer TransactionRecord —
/// évite un JOIN sur le chemin critique du Worker, et permet de supprimer
/// une ligne de PendingTransactions indépendamment du cycle de vie de
/// TransactionRecord (qui, lui, reste pour l'historique).
/// </summary>
public sealed class PendingTransactionRecord
{
    /// <summary>Clé primaire locale — générée à l'insertion.</summary>
    public required Guid Id { get; set; }

    /// <summary>Correspond à Transaction.TransactionId — pas une clé étrangère stricte.</summary>
    public required string TransactionId { get; set; }

    public required string Operator { get; set; }

    // ── Données complètes de la transaction — pour reconstruire Transaction (Domain) ──
    public required string ClientToken { get; set; }
    public required decimal Amount { get; set; }
    public required string Currency { get; set; }
    public required string Channel { get; set; }
    public required string Zone { get; set; }
    public required string DeviceId { get; set; }
    public required bool SimChanged72h { get; set; }
    public DateTime? SimChangedAt { get; set; }
    public required string BeneficiaryToken { get; set; }
    public required bool BeneficiaryIsMerchant { get; set; }
    public string? AgentId { get; set; }
    public required bool UssdSession { get; set; }
    public required DateTime Timestamp { get; set; }

    // ── Gestion de la file ────────────────────────────────────────────────────

    public required DateTime EnqueuedAt { get; set; }

    /// <summary>
    /// Nombre de tentatives de rescoring échouées.
    /// Au-delà du seuil maxAttempts (configuré dans PendingTransactionWorker),
    /// la ligne est sortie de la file et loggée en erreur pour intervention
    /// manuelle — évite une boucle infinie sur une transaction qui échoue
    /// systématiquement (payload corrompu, bug de désérialisation).
    /// </summary>
    public required int AttemptCount { get; set; }

    public DateTime? LastAttemptAt { get; set; }
}