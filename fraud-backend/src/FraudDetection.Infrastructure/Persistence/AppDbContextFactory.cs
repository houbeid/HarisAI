using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace FraudDetection.Infrastructure.Persistence;

/// <summary>
/// Fabrique de conception (design-time) pour AppDbContext — utilisée
/// EXCLUSIVEMENT par l'outil dotnet-ef (migrations add, database update),
/// jamais par l'application en production. En production, AppDbContext
/// est construit via l'injection de dépendances configurée dans
/// Program.cs (API et Worker), avec la vraie chaîne de connexion du site.
///
/// POURQUOI CETTE CLASSE EST NÉCESSAIRE : dotnet-ef doit pouvoir
/// instancier AppDbContext pour comparer le modèle EF Core au schéma
/// existant et générer une migration, sans démarrer toute l'application
/// (DI complète, Serilog, Polly, etc.). Cette fabrique fournit un chemin
/// minimal et indépendant du host applicatif.
///
/// La chaîne de connexion ici ne sert QU'À LA GÉNÉRATION de la migration —
/// aucune vraie donnée n'est lue ni écrite via ce chemin. Une base
/// PostgreSQL locale (Docker) suffit, même vide.
/// </summary>
public sealed class AppDbContextFactory : IDesignTimeDbContextFactory<AppDbContext>
{
    public AppDbContext CreateDbContext(string[] args)
    {
        var optionsBuilder = new DbContextOptionsBuilder<AppDbContext>();

        // Chaîne de connexion de conception — surchargeable via variable
        // d'environnement si besoin (ex: CI/CD), sinon valeur locale par défaut.
        var connectionString = Environment.GetEnvironmentVariable("EFCORE_DESIGN_TIME_CONNECTION")
            ?? "Host=localhost;Port=5432;Database=harisai_dev;Username=postgres;Password=devpassword";

        optionsBuilder
            .UseNpgsql(connectionString)
            .UseSnakeCaseNamingConvention();

        return new AppDbContext(optionsBuilder.Options);
    }
}