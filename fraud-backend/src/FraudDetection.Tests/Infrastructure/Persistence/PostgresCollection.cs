using Xunit;

namespace FraudDetection.Tests.Infrastructure.Persistence;

/// <summary>
/// Définition de collection xUnit — force AlertRepositoryTests,
/// TransactionRepositoryTests et PendingTransactionRepositoryTests à
/// partager UNE SEULE instance de PostgresFixture (un seul conteneur
/// Docker) au lieu d'un conteneur par classe.
///
/// EFFET SECONDAIRE VOULU : xUnit exécute automatiquement les classes
/// d'une même collection de façon SÉQUENTIELLE, jamais en parallèle entre
/// elles — évite toute collision sur les données partagées du conteneur,
/// en complément de PostgresFixture.CleanupAsync() appelé au début de
/// chaque test individuel.
///
/// Ce fichier ne contient aucune logique — juste l'attribut qui relie
/// le nom "PostgresCollection" à PostgresFixture. Voir la documentation
/// xUnit sur ICollectionFixture pour le mécanisme complet.
/// </summary>
[CollectionDefinition("PostgresCollection")]
public sealed class PostgresCollection : ICollectionFixture<PostgresFixture>
{
    // Intentionnellement vide — cette classe n'existe que pour porter
    // l'attribut CollectionDefinition.
}