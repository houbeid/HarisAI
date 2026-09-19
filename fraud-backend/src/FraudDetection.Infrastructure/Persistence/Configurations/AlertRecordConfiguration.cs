using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace FraudDetection.Infrastructure.Persistence.Configurations;

/// <summary>
/// Mapping EF Core pour AlertRecord → table "alerts" dans le schéma fraud_backend.
/// </summary>
public sealed class AlertRecordConfiguration : IEntityTypeConfiguration<AlertRecord>
{
    public void Configure(EntityTypeBuilder<AlertRecord> builder)
    {
        builder.ToTable("alerts");

        builder.HasKey(a => a.Id);

        builder.Property(a => a.AlertId)
            .HasMaxLength(50);

        builder.Property(a => a.TransactionId)
            .HasMaxLength(100);

        builder.Property(a => a.Operator)
            .HasMaxLength(50);

        // precision(18,2) — cohérent avec le montant maximal réaliste d'une
        // transaction mobile money en MRU, deux décimales suffisent (pas de
        // sous-unité inférieure au centime d'Ouguiya utilisée en pratique).
        builder.Property(a => a.AmountValue)
            .HasPrecision(18, 2);

        builder.Property(a => a.Decision)
            .HasMaxLength(20);

        builder.Property(a => a.FraudType)
            .HasMaxLength(50);

        builder.Property(a => a.Status)
            .HasMaxLength(20);

        builder.Property(a => a.ReviewedBy)
            .HasMaxLength(255); // email agent de conformité

        builder.Property(a => a.ReviewNote)
            .HasMaxLength(2000);

        // AlertId est un identifiant métier FastAPI — unique mais pas clé primaire,
        // car Id (Guid) est généré localement à la construction de l'entité Alert
        // (voir Alert.cs, Domain) avant même la persistance.
        builder.HasIndex(a => a.AlertId)
            .IsUnique()
            .HasDatabaseName("ix_alerts_alert_id");

        // Utilisé par GetByTransactionIdAsync (idempotence — éviter la double alerte
        // sur un retry de webhook opérateur).
        builder.HasIndex(a => a.TransactionId)
            .IsUnique()
            .HasDatabaseName("ix_alerts_transaction_id");

        // Utilisé par GetByStatusAsync (fraud-dashboard) — filtrage fréquent
        // par statut + opérateur, trié par date de création.
        builder.HasIndex(a => new { a.Operator, a.Status, a.CreatedAt })
            .HasDatabaseName("ix_alerts_operator_status_created_at");
    }
}