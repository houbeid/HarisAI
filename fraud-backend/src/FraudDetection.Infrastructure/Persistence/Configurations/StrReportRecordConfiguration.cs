using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace FraudDetection.Infrastructure.Persistence.Configurations;

/// <summary>
/// Mapping EF Core pour StrReportRecord → table "str_reports"
/// dans le schéma fraud_backend.
/// </summary>
public sealed class StrReportRecordConfiguration : IEntityTypeConfiguration<StrReportRecord>
{
    public void Configure(EntityTypeBuilder<StrReportRecord> builder)
    {
        builder.ToTable("str_reports");

        builder.HasKey(r => r.ReportId);

        builder.Property(r => r.ReportId)
            .HasMaxLength(100);

        builder.Property(r => r.AlertId)
            .HasMaxLength(50);

        builder.Property(r => r.TransactionId)
            .HasMaxLength(100);

        builder.Property(r => r.Operator)
            .HasMaxLength(50);

        builder.Property(r => r.FraudType)
            .HasMaxLength(50);

        builder.Property(r => r.Decision)
            .HasMaxLength(20);

        builder.Property(r => r.ConfirmedBy)
            .HasMaxLength(255);

        builder.Property(r => r.AgentNote)
            .HasMaxLength(2000);

        // Un seul rapport par alerte — cohérent avec le fait qu'une alerte
        // ne peut être confirmée qu'une seule fois (Alert.Confirm() lève
        // une exception si déjà traitée, voir Domain).
        builder.HasIndex(r => r.AlertId)
            .IsUnique()
            .HasDatabaseName("ix_str_reports_alert_id");

        // Utilisé par GetStrReportsHandler — historique des rapports
        // par opérateur, trié par date de génération.
        builder.HasIndex(r => new { r.Operator, r.GeneratedAt })
            .HasDatabaseName("ix_str_reports_operator_generated_at");

        // Utile pour un futur job de transmission BCM qui interrogerait
        // "quels rapports restent à transmettre ?" une fois
        // IBcmReportingService implémenté.
        builder.HasIndex(r => new { r.Operator, r.Transmitted })
            .HasDatabaseName("ix_str_reports_operator_transmitted");
    }
}