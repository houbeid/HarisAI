using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace FraudDetection.Infrastructure.Persistence.Configurations;

/// <summary>
/// Mapping EF Core pour PendingTransactionRecord → table "pending_transactions"
/// dans le schéma fraud_backend.
///
/// Cette table est consommée exclusivement via SELECT ... FOR UPDATE SKIP LOCKED
/// (requête SQL brute dans PendingTransactionRepository, pas via LINQ standard —
/// EF Core ne génère pas nativement cette syntaxe). La configuration ici ne fait
/// que définir le schéma de la table ; le verrouillage concurrent est géré
/// directement en SQL dans le repository.
/// </summary>
public sealed class PendingTransactionRecordConfiguration
    : IEntityTypeConfiguration<PendingTransactionRecord>
{
    public void Configure(EntityTypeBuilder<PendingTransactionRecord> builder)
    {
        builder.ToTable("pending_transactions");

        builder.HasKey(p => p.Id);

        builder.Property(p => p.TransactionId)
            .HasMaxLength(100);

        builder.Property(p => p.Operator)
            .HasMaxLength(50);

        builder.Property(p => p.ClientToken)
            .HasMaxLength(128);

        builder.Property(p => p.Amount)
            .HasPrecision(18, 2);

        builder.Property(p => p.Currency)
            .HasMaxLength(3);

        builder.Property(p => p.Channel)
            .HasMaxLength(20);

        builder.Property(p => p.Zone)
            .HasMaxLength(100);

        builder.Property(p => p.DeviceId)
            .HasMaxLength(128);

        builder.Property(p => p.BeneficiaryToken)
            .HasMaxLength(128);

        builder.Property(p => p.AgentId)
            .HasMaxLength(50);

        // Un même TransactionId ne doit apparaître qu'une fois dans la file —
        // EnqueueAsync (IPendingTransactionQueue) est idempotent, cette contrainte
        // l'impose aussi au niveau base pour un filet de sécurité supplémentaire.
        builder.HasIndex(p => p.TransactionId)
            .IsUnique()
            .HasDatabaseName("ix_pending_transactions_transaction_id");

        // Utilisé par DequeueAsync — SELECT FOR UPDATE SKIP LOCKED filtre
        // typiquement par opérateur puis trie par EnqueuedAt (FIFO).
        builder.HasIndex(p => new { p.Operator, p.EnqueuedAt })
            .HasDatabaseName("ix_pending_transactions_operator_enqueued_at");
    }
}