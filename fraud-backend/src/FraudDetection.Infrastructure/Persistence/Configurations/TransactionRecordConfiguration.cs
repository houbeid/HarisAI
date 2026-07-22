using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace FraudDetection.Infrastructure.Persistence.Configurations;

/// <summary>
/// Mapping EF Core pour TransactionRecord → table "transactions"
/// dans le schéma fraud_backend.
/// </summary>
public sealed class TransactionRecordConfiguration : IEntityTypeConfiguration<TransactionRecord>
{
    public void Configure(EntityTypeBuilder<TransactionRecord> builder)
    {
        builder.ToTable("transactions");

        builder.HasKey(t => t.TransactionId);

        builder.Property(t => t.TransactionId)
            .HasMaxLength(100);

        builder.Property(t => t.ClientToken)
            .HasMaxLength(128);

        builder.Property(t => t.Amount)
            .HasPrecision(18, 2); // MRU — pas de décimales fractionnaires exotiques

        builder.Property(t => t.Currency)
            .HasMaxLength(3); // ISO 4217 — "MRU"

        builder.Property(t => t.Channel)
            .HasMaxLength(20);

        builder.Property(t => t.Zone)
            .HasMaxLength(100);

        builder.Property(t => t.Operator)
            .HasMaxLength(50);

        builder.Property(t => t.DeviceId)
            .HasMaxLength(128);

        builder.Property(t => t.BeneficiaryToken)
            .HasMaxLength(128);

        builder.Property(t => t.AgentId)
            .HasMaxLength(50);

        builder.Property(t => t.Decision)
            .HasMaxLength(20);

        builder.Property(t => t.FraudType)
            .HasMaxLength(50);

        builder.Property(t => t.AlertId)
            .HasMaxLength(50);

        builder.Property(t => t.ModelVersion)
            .HasMaxLength(20);

        builder.Property(t => t.NotificationStatus)
            .HasMaxLength(20);

        // Index utilisés par GetHistoryAsync (ITransactionRepository) —
        // filtrage fréquent par opérateur + décision, trié par date.
        builder.HasIndex(t => new { t.Operator, t.ReceivedAt })
            .HasDatabaseName("ix_transactions_operator_received_at");

        builder.HasIndex(t => new { t.Operator, t.Decision })
            .HasDatabaseName("ix_transactions_operator_decision");

        // Utilisé par GetFailedNotificationsAsync — retrouver rapidement
        // les notifications à retenter par PendingTransactionWorker.
        builder.HasIndex(t => new { t.Operator, t.NotificationStatus })
            .HasDatabaseName("ix_transactions_operator_notification_status");
    }
}