using FraudDetection.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Testcontainers.PostgreSql;
using Xunit;

namespace FraudDetection.Tests.Infrastructure.Persistence;

/// <summary>
/// Fixture xUnit partagée par toutes les classes de tests de repository.
/// Lance un vrai conteneur PostgreSQL (image officielle) le temps de la
/// collection de tests, applique le schéma via EnsureCreatedAsync, puis
/// détruit le conteneur à la fin.
///
/// POURQUOI UN VRAI POSTGRESQL ET PAS InMemory :
/// SELECT ... FOR UPDATE SKIP LOCKED (PendingTransactionRepository) est
/// une syntaxe SQL native PostgreSQL — le provider InMemory ne peut pas
/// l'exécuter. Tester contre un faux SQL donnerait une fausse confiance
/// sur le mécanisme central qui garantit l'absence de double traitement
/// avec plusieurs pods Kubernetes.
///
/// UTILISATION : implémenter IClassFixture&lt;PostgresFixture&gt; dans chaque
/// classe de test de repository. Chaque test doit nettoyer ses propres
/// données (voir CleanupAsync) pour rester indépendant des autres tests
/// dans la même classe — pas de conteneur par test (trop lent), mais
/// pas de pollution inter-tests non plus.
/// </summary>
public sealed class PostgresFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer _container = new PostgreSqlBuilder()
        .WithImage("postgres:16-alpine")
        .WithDatabase("harisai_test")
        .WithUsername("test")
        .WithPassword("test")
        .Build();

    public AppDbContext DbContext { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        await _container.StartAsync();

        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseNpgsql(_container.GetConnectionString())
            .UseSnakeCaseNamingConvention()
            .Options;

        DbContext = new AppDbContext(options);

        // EnsureCreatedAsync applique le modèle EF Core directement (DDL),
        // sans passer par les migrations — suffisant pour les tests, qui
        // n'ont pas besoin de valider le chemin de migration lui-même.
        await DbContext.Database.EnsureCreatedAsync();
    }

    public async Task DisposeAsync()
    {
        await DbContext.DisposeAsync();
        await _container.DisposeAsync();
    }

    /// <summary>
    /// Vide toutes les tables entre les tests d'une même classe pour
    /// garantir l'indépendance — appelé explicitement en début de chaque
    /// test plutôt qu'en Dispose, pour un contrôle explicite et lisible.
    /// </summary>
    public async Task CleanupAsync()
    {
        DbContext.PendingTransactions.RemoveRange(DbContext.PendingTransactions);
        DbContext.Alerts.RemoveRange(DbContext.Alerts);
        DbContext.Transactions.RemoveRange(DbContext.Transactions);
        DbContext.StrReports.RemoveRange(DbContext.StrReports);
        await DbContext.SaveChangesAsync();

        // Évite que le tracking EF Core d'un test précédent interfère
        // avec les assertions du test suivant (entités déjà trackées).
        DbContext.ChangeTracker.Clear();
    }
}