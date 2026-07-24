namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Port de notification temps réel des agents de conformité connectés
/// à fraud-dashboard. Découple CreateAlertHandler de SignalR — l'Application
/// ne doit jamais dépendre directement d'un mécanisme de transport
/// spécifique à la présentation (AlertHub vit dans FraudDetection.API).
///
/// L'implémentation concrète (SignalRAlertNotifier, API/Hubs) utilise
/// IHubContext&lt;AlertHub&gt; pour diffuser via SignalR, avec le backplane
/// Redis déjà câblé (RedisService.cs) pour atteindre tous les pods.
///
/// SI SIGNALR ÉCHOUE (ex: Redis backplane indisponible), la notification
/// ne doit jamais bloquer la création de l'alerte elle-même — l'implémentation
/// doit intercepter ses propres erreurs et logger, jamais laisser une
/// exception remonter à CreateAlertHandler.
/// </summary>
public interface IAlertNotifier
{
    /// <summary>
    /// Notifie tous les agents connectés qu'une nouvelle alerte a été créée.
    /// Appelé depuis CreateAlertHandler immédiatement après la persistance
    /// réussie de l'alerte (jamais avant — un agent ne doit jamais être
    /// notifié d'une alerte qui n'existe pas encore en base).
    /// </summary>
    Task NotifyNewAlertAsync(
        string alertId,
        string transactionId,
        string decision,
        int score,
        string? fraudType,
        CancellationToken cancellationToken = default);
}