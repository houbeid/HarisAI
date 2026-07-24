using FraudDetection.Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Infrastructure.Observability;

/// <summary>
/// BackgroundService qui interroge périodiquement IPendingTransactionQueue
/// et IAlertRepository pour maintenir à jour les jauges Prometheus
/// fraudbackend_pending_queue_size et fraudbackend_alerts_pending_count.
///
/// POURQUOI UN POLLER SÉPARÉ PLUTÔT QUE D'INSTRUMENTER LES REPOSITORIES :
/// GetQueueSizeAsync() et CountPendingAsync() existent déjà en tant que
/// méthodes publiques du contrat (IPendingTransactionQueue, IAlertRepository).
/// Les interroger périodiquement depuis un composant séparé évite de
/// modifier PendingTransactionRepository et AlertRepository — déjà écrits
/// et testés — juste pour de l'observabilité. Cohérent avec le modèle
/// "pull" que Prometheus privilégie nativement.
///
/// UN SEUL OPÉRATEUR PAR SITE : conformément à la topologie de déploiement
/// (un site = un opérateur), le code opérateur à surveiller est lu depuis
/// la configuration ("Operator:Code", injecté par l'overlay Kustomize du
/// site) plutôt qu'énuméré dynamiquement — il n'y a jamais qu'un seul
/// opérateur actif par déploiement.
/// </summary>
public sealed class PendingMetricsPoller : BackgroundService
{
    private const string OperatorCodeConfigKey = "Operator:Code";
    private const string PollIntervalConfigKey = "Observability:MetricsPollIntervalSeconds";
    private const int DefaultPollIntervalSeconds = 30;

    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IMetricsCollector _metricsCollector;
    private readonly IConfiguration _configuration;
    private readonly ILogger<PendingMetricsPoller> _logger;

    public PendingMetricsPoller(
        IServiceScopeFactory scopeFactory,
        IMetricsCollector metricsCollector,
        IConfiguration configuration,
        ILogger<PendingMetricsPoller> logger)
    {
        _scopeFactory = scopeFactory;
        _metricsCollector = metricsCollector;
        _configuration = configuration;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var operatorCode = _configuration[OperatorCodeConfigKey];
        if (string.IsNullOrWhiteSpace(operatorCode))
        {
            _logger.LogWarning(
                "Aucun code opérateur configuré ({ConfigKey}) — " +
                "PendingMetricsPoller ne peut pas démarrer et reste inactif.",
                OperatorCodeConfigKey);
            return;
        }

        var pollInterval = TimeSpan.FromSeconds(
            _configuration.GetValue(PollIntervalConfigKey, DefaultPollIntervalSeconds));

        _logger.LogInformation(
            "PendingMetricsPoller démarré — Operator={OperatorCode} Interval={Interval}",
            operatorCode, pollInterval);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await PollOnceAsync(operatorCode, stoppingToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // Une erreur de polling (ex: base de données temporairement
                // indisponible) ne doit jamais arrêter le poller — juste
                // manquer un cycle et réessayer au suivant.
                _logger.LogError(ex,
                    "Erreur lors du polling des métriques pour {OperatorCode}. " +
                    "Nouvelle tentative au prochain cycle.",
                    operatorCode);
            }

            try
            {
                await Task.Delay(pollInterval, stoppingToken);
            }
            catch (OperationCanceledException)
            {
                // Arrêt normal du service — pas une erreur.
                break;
            }
        }

        _logger.LogInformation("PendingMetricsPoller arrêté.");
    }

    private async Task PollOnceAsync(string operatorCode, CancellationToken cancellationToken)
    {
        // Un scope DI dédié par cycle — IPendingTransactionQueue et
        // IAlertRepository dépendent d'AppDbContext, enregistré Scoped
        // (jamais Singleton, voir la contrainte de statelessness K8s déjà
        // actée). Un BackgroundService est lui-même Singleton, donc il doit
        // créer explicitement un scope pour résoudre des dépendances Scoped.
        using var scope = _scopeFactory.CreateScope();

        var pendingQueue = scope.ServiceProvider.GetRequiredService<IPendingTransactionQueue>();
        var alertRepository = scope.ServiceProvider.GetRequiredService<IAlertRepository>();

        var queueSize = await pendingQueue.GetQueueSizeAsync(operatorCode, cancellationToken);
        var alertsPending = await alertRepository.CountPendingAsync(operatorCode, cancellationToken);

        _metricsCollector.SetPendingQueueSize(operatorCode, queueSize);
        _metricsCollector.SetAlertsPendingCount(operatorCode, alertsPending);

        _logger.LogDebug(
            "Métriques mises à jour — Operator={OperatorCode} QueueSize={QueueSize} " +
            "AlertsPending={AlertsPending}",
            operatorCode, queueSize, alertsPending);
    }
}