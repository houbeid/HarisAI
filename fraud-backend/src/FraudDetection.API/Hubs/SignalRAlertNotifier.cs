using FraudDetection.Application.Interfaces;
using Microsoft.AspNetCore.SignalR;

namespace FraudDetection.API.Hubs;

/// <summary>
/// Implémentation de IAlertNotifier via SignalR (IHubContext&lt;AlertHub&gt;).
/// Vit dans FraudDetection.API — pas dans Infrastructure — car AlertHub
/// lui-même est un type de présentation (hérite de Hub, ASP.NET Core),
/// pas un composant d'infrastructure réutilisable indépendamment du web host.
///
/// GARANTIE DOCUMENTÉE DANS IAlertNotifier : ne laisse jamais une exception
/// remonter à CreateAlertHandler — toute erreur (backplane Redis indisponible,
/// connexion SignalR interrompue, etc.) est interceptée et loguée ici.
/// La création de l'alerte doit toujours réussir même si sa diffusion
/// temps réel échoue.
/// </summary>
public sealed class SignalRAlertNotifier : IAlertNotifier
{
    private const string ClientMethodName = "ReceiveAlert";

    private readonly IHubContext<AlertHub> _hubContext;
    private readonly ILogger<SignalRAlertNotifier> _logger;

    public SignalRAlertNotifier(
        IHubContext<AlertHub> hubContext,
        ILogger<SignalRAlertNotifier> logger)
    {
        _hubContext = hubContext;
        _logger = logger;
    }

    public async Task NotifyNewAlertAsync(
        string alertId,
        string transactionId,
        string decision,
        int score,
        string? fraudType,
        CancellationToken cancellationToken = default)
    {
        try
        {
            var payload = new
            {
                alertId,
                transactionId,
                decision,
                score,
                fraudType
            };

            // Diffusion à TOUS les clients connectés à cette instance — voir
            // AlertHub.cs pour le raisonnement (pas de groupes par opérateur,
            // topologie un site = un opérateur). Le backplane Redis déjà câblé
            // (RedisService.cs) garantit que les agents connectés à d'autres
            // pods reçoivent aussi ce message.
            await _hubContext.Clients.All.SendAsync(
                ClientMethodName, payload, cancellationToken);

            _logger.LogDebug(
                "Alerte diffusée via SignalR — AlertId={AlertId} Decision={Decision}",
                alertId, decision);
        }
        catch (Exception ex)
        {
            // Ne remonte JAMAIS — voir la garantie documentée dans IAlertNotifier.
            // Une notification temps réel manquée est dégradante, pas critique ;
            // l'agent verra quand même l'alerte au prochain GET /alerts.
            _logger.LogError(ex,
                "Échec de diffusion SignalR pour AlertId={AlertId} — " +
                "l'alerte reste visible via GET /alerts malgré cet échec.",
                alertId);
        }
    }
}