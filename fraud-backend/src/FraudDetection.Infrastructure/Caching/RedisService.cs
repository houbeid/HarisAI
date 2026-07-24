using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.DependencyInjection;

namespace FraudDetection.Infrastructure.Caching;

/// <summary>
/// Câble Redis comme backplane SignalR pour AlertHub.
///
/// POURQUOI C'EST OBLIGATOIRE DÈS QU'IL Y A PLUSIEURS PODS :
/// SignalR maintient les connexions WebSocket ouvertes en mémoire, par pod.
/// Sans backplane partagé, un agent de conformité connecté au pod A ne
/// recevra JAMAIS une alerte poussée par un traitement exécuté sur le pod B —
/// silencieusement, sans erreur visible. Le backplane Redis synchronise les
/// messages SignalR entre tous les pods, quel que soit celui qui a initié
/// l'envoi.
///
/// PÉRIMÈTRE ACTUEL DE CE FICHIER : uniquement le câblage du backplane.
/// Aucun cache métier générique n'est implémenté ici — aucun consommateur
/// concret n'a été identifié à ce jour dans le code déjà écrit (toute la
/// persistance métier utilise PostgreSQL, voir Persistence/). Si un besoin
/// de cache apparaît plus tard (ex: résultats fréquemment consultés par
/// fraud-dashboard), ce fichier sera étendu à ce moment-là avec un vrai
/// cas d'usage, pas en anticipation.
///
/// PRÉFIXE DE CLÉ : Redis est partagé avec fraud-ml-service (Python), qui
/// utilise déjà les préfixes harisai:{operateur}:profile:{token} et
/// harisai:{operateur}:beneficiary:{token}. SignalR gère ses propres clés
/// de backplane en interne — pas de collision avec les clés Python. Si un
/// futur cache métier .NET est ajouté, il devra explicitement préfixer ses
/// clés avec "fraud-backend:" pour rester dans cette même logique d'isolation.
/// </summary>
public static class RedisService
{
    /// <summary>
    /// Enregistre le backplane Redis pour SignalR.
    /// À appeler dans Program.cs après AddSignalR() :
    ///
    ///   builder.Services.AddSignalR()
    ///       .AddRedisBackplane(redisConnectionString);
    /// </summary>
    public static ISignalRServerBuilder AddRedisBackplane(
        this ISignalRServerBuilder signalRBuilder,
        string redisConnectionString)
    {
        if (string.IsNullOrWhiteSpace(redisConnectionString))
        {
            throw new ArgumentException(
                "La chaîne de connexion Redis pour le backplane SignalR " +
                "ne peut pas être vide. Vérifier la configuration " +
                "(ConnectionStrings:Redis).",
                nameof(redisConnectionString));
        }

        return signalRBuilder.AddStackExchangeRedis(redisConnectionString, options =>
        {
            // Canal préfixé pour éviter toute collision si, un jour, un autre
            // service .NET utilise aussi SignalR sur la même instance Redis
            // partagée avec Python.
            options.Configuration.ChannelPrefix =
                StackExchange.Redis.RedisChannel.Literal("fraud-backend-signalr");
        });
    }
}