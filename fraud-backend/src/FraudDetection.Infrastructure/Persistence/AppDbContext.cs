using FraudDetection.Infrastructure.Persistence.Records;
using Microsoft.EntityFrameworkCore;

namespace FraudDetection.Infrastructure.Persistence;

/// <summary>
/// Contexte EF Core pour fraud-backend.
/// Schéma PostgreSQL "fraud_backend" — distinct de "ml_audit" (Python).
/// Base PostgreSQL locale au site (un déploiement = un opérateur), jamais partagée
/// entre banques — cohérent avec la topologie on-premise isolée par site.
///
/// DÉCISION DE CONCEPTION : ce contexte ne mappe JAMAIS les entités du Domain
/// (Transaction, Alert) directement. Il mappe des Records de persistance dédiés
/// (TransactionRecord, AlertRecord, PendingTransactionRecord) définis dans
/// Persistence/Records/. Les repositories (TransactionRepository, AlertRepository,
/// PendingTransactionRepository) sont responsables du mapping Domain ↔ Record.
///
/// RAISON : les entités Domain ont des constructeurs avec validation stricte et
/// des Value Objects sans constructeur sans paramètre (Money, TokenHash, RiskScore).
/// Les mapper directement nécessiterait d'affaiblir leur encapsulation pour EF Core.
/// Le Domain reste pur — zéro dépendance technique, y compris envers EF Core.
/// </summary>
public sealed class AppDbContext : DbContext
{
    private const string Schema = "fraud_backend";

    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options)
    {
    }

    public DbSet<TransactionRecord> Transactions => Set<TransactionRecord>();
    public DbSet<AlertRecord> Alerts => Set<AlertRecord>();
    public DbSet<PendingTransactionRecord> PendingTransactions => Set<PendingTransactionRecord>();
    public DbSet<StrReportRecord> StrReports => Set<StrReportRecord>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.HasDefaultSchema(Schema);

        // Applique toutes les IEntityTypeConfiguration<T> définies dans
        // Persistence/Configurations/ — pas de configuration inline ici,
        // pour garder ce fichier stable même si de nouveaux Records apparaissent.
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(AppDbContext).Assembly);

        base.OnModelCreating(modelBuilder);
    }
}