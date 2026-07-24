using FraudDetection.Application.Interfaces;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Worker;

/// <summary>
/// Implémentation "no-op" de IAlertNotifier pour FraudDetection.Worker.
///
/// POURQUOI PAS SignalRAlertNotifier ICI : cette classe vit dans
/// FraudDetection.API (dépend d'AlertHub, également dans API). Le Worker
/// est un processus/pod SÉPARÉ de l'API (replicas:1, déploiement
/// Kubernetes distinct) — le coupler à des types de la couche présentation
/// API créerait une dépendance architecturale incorrecte (Worker → API).
///
/// CONSÉQUENCE ASSUMÉE : une alerte créée pendant un rescoring en
/// arrière-plan (transaction qui était en file de résilience, FastAPI
/// de nouveau disponible) N'EST PAS poussée en temps réel aux agents
/// connectés. L'agent la verra au prochain GET /alerts (rafraîchissement
/// du dashboard), pas instantanément comme pour une alerte créée en
/// direct via TransactionController.
///
/// AMÉLIORATION FUTURE POSSIBLE : le Worker pourrait se connecter au
/// même backplane Redis que SignalR (StackExchange.Redis pub/sub) sans
/// dépendre du type AlertHub lui-même, moyennant une abstraction partagée —
/// non implémenté pour l'instant, cette limite étant jugée acceptable
/// (les rescoring en attente sont déjà une situation dégradée par
/// définition, un léger délai d'affichage supplémentaire est mineur
/// en comparaison).
/// </summary>
public sealed class NoOpAlertNotifier : IAlertNotifier
{
    private readonly ILogger<NoOpAlertNotifier> _logger;

    public NoOpAlertNotifier(ILogger<NoOpAlertNotifier> logger)
    {
        _logger = logger;
    }

    public Task NotifyNewAlertAsync(
        string alertId,
        string transactionId,
        string decision,
        int score,
        string? fraudType,
        CancellationToken cancellationToken = default)
    {
        _logger.LogInformation(
            "Alerte {AlertId} créée via rescoring en arrière-plan (Worker) — " +
            "pas de notification SignalR temps réel depuis ce processus. " +
            "Visible au prochain GET /alerts.",
            alertId);

        return Task.CompletedTask;
    }
}