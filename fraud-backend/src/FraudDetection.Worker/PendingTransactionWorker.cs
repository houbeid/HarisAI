using FraudDetection.Application.Commands.CreateAlert;
using FraudDetection.Application.Interfaces;
using MediatR;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Serilog.Context;

namespace FraudDetection.Worker;

/// <summary>
/// BackgroundService qui consomme la file de résilience locale
/// (IPendingTransactionQueue) et retente le scoring des transactions
/// mises en attente pendant une panne de fraud-ml-service.
///
/// FLUX PAR CYCLE :
///   1. Vérifier IMlScoringService.IsHealthyAsync() — si FastAPI est
///      toujours down, ne pas dépiler (évite un aller-retour DB inutile
///      pour re-requeue immédiatement chaque transaction).
///   2. DequeueAsync() un lot (SELECT FOR UPDATE SKIP LOCKED — sûr même
///      avec plusieurs pods, bien que ce Worker tourne en replicas:1).
///   3. Pour chaque transaction : nouveau CorrelationId (ce n'est plus
///      lié à la requête HTTP d'origine, qui est terminée depuis longtemps),
///      ré-appel AnalyzeAsync.
///   4. Toujours DefaultReview → RequeueAsync (FastAPI encore indisponible
///      ou en train de redevenir stable — laisse une chance au prochain cycle).
///   5. Vrai score reçu → UpdateScoreAsync + AcknowledgeAsync + CreateAlertCommand
///      si REVIEW/BLOCK (réutilise la même logique Application que le flux
///      temps réel, pas de duplication de la création d'alerte).
/// </summary>
public sealed class PendingTransactionWorker : BackgroundService
{
    private const string OperatorCodeConfigKey = "Operator:Code";
    private const string PollIntervalConfigKey = "Worker:PollIntervalSeconds";
    private const string BatchSizeConfigKey = "Worker:BatchSize";
    private const int DefaultPollIntervalSeconds = 15;
    private const int DefaultBatchSize = 10;

    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IConfiguration _configuration;
    private readonly ILogger<PendingTransactionWorker> _logger;

    public PendingTransactionWorker(
        IServiceScopeFactory scopeFactory,
        IConfiguration configuration,
        ILogger<PendingTransactionWorker> logger)
    {
        _scopeFactory = scopeFactory;
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
                "PendingTransactionWorker ne peut pas démarrer et reste inactif.",
                OperatorCodeConfigKey);
            return;
        }

        var pollInterval = TimeSpan.FromSeconds(
            _configuration.GetValue(PollIntervalConfigKey, DefaultPollIntervalSeconds));
        var batchSize = _configuration.GetValue(BatchSizeConfigKey, DefaultBatchSize);

        _logger.LogInformation(
            "PendingTransactionWorker démarré — Operator={OperatorCode} " +
            "Interval={Interval} BatchSize={BatchSize}",
            operatorCode, pollInterval, batchSize);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await ProcessOnceAsync(operatorCode, batchSize, stoppingToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // Une erreur inattendue sur un cycle ne doit jamais arrêter
                // le Worker définitivement — juste manquer ce cycle et
                // réessayer au suivant, même principe que PendingMetricsPoller.
                _logger.LogError(ex,
                    "Erreur lors du traitement de la file de résilience pour " +
                    "{OperatorCode}. Nouvelle tentative au prochain cycle.",
                    operatorCode);
            }

            try
            {
                await Task.Delay(pollInterval, stoppingToken);
            }
            catch (OperationCanceledException)
            {
                break; // Arrêt normal du service — pas une erreur.
            }
        }

        _logger.LogInformation("PendingTransactionWorker arrêté.");
    }

    private async Task ProcessOnceAsync(
        string operatorCode, int batchSize, CancellationToken cancellationToken)
    {
        using var scope = _scopeFactory.CreateScope();

        var mlScoringService = scope.ServiceProvider.GetRequiredService<IMlScoringService>();

        // Ne pas dépiler si FastAPI est toujours indisponible — évite un
        // aller-retour DB (dequeue + requeue immédiat) sans valeur ajoutée.
        var isHealthy = await mlScoringService.IsHealthyAsync(cancellationToken);
        if (!isHealthy)
        {
            _logger.LogDebug(
                "fraud-ml-service toujours indisponible — cycle ignoré pour {OperatorCode}.",
                operatorCode);
            return;
        }

        var pendingQueue = scope.ServiceProvider.GetRequiredService<IPendingTransactionQueue>();
        var transactionRepository = scope.ServiceProvider.GetRequiredService<ITransactionRepository>();
        var mediator = scope.ServiceProvider.GetRequiredService<IMediator>();

        var batch = await pendingQueue.DequeueAsync(batchSize, cancellationToken);
        if (batch.Count == 0)
        {
            return;
        }

        _logger.LogInformation(
            "Retraitement de {Count} transaction(s) en attente pour {OperatorCode}.",
            batch.Count, operatorCode);

        foreach (var transaction in batch)
        {
            // Nouveau CorrelationId par tentative — la requête HTTP d'origine
            // qui a mis cette transaction en file est terminée depuis
            // longtemps, ce rescoring est un nouvel événement à part entière.
            var correlationId = $"worker-retry-{Guid.NewGuid()}";

            using (LogContext.PushProperty("CorrelationId", correlationId))
            {
                await ProcessTransactionAsync(
                    transaction.TransactionId,
                    transaction,
                    correlationId,
                    mlScoringService,
                    pendingQueue,
                    transactionRepository,
                    mediator,
                    cancellationToken);
            }
        }
    }

    private async Task ProcessTransactionAsync(
        string transactionId,
        Domain.Entities.Transaction transaction,
        string correlationId,
        IMlScoringService mlScoringService,
        IPendingTransactionQueue pendingQueue,
        ITransactionRepository transactionRepository,
        IMediator mediator,
        CancellationToken cancellationToken)
    {
        var score = await mlScoringService.AnalyzeAsync(
            transaction, correlationId, cancellationToken);

        var isDefaultReview = score.FraudType == "UNAVAILABLE";

        if (isDefaultReview)
        {
            // Toujours indisponible malgré le healthcheck positif au début
            // du cycle (panne survenue entre-temps) — remise en file,
            // RequeueAsync gère elle-même le compteur de tentatives et
            // le seuil MaxAttempts (voir PendingTransactionRepository).
            await pendingQueue.RequeueAsync(transactionId, cancellationToken);

            _logger.LogWarning(
                "Rescoring toujours en échec pour TransactionId={TransactionId} — " +
                "remise en file.",
                transactionId);
            return;
        }

        await transactionRepository.UpdateScoreAsync(
            transactionId, score, cancellationToken);
        await pendingQueue.AcknowledgeAsync(transactionId, cancellationToken);

        _logger.LogInformation(
            "Rescoring réussi — TransactionId={TransactionId} Decision={Decision} " +
            "Score={Score}",
            transactionId, score.Decision, score.Score);

        if (score.RequiresHumanReview && score.AlertId is not null)
        {
            await mediator.Send(
                new CreateAlertCommand(
                    alertId: score.AlertId,
                    transactionId: transactionId,
                    operatorCode: transaction.Operator,
                    score: score),
                cancellationToken);
        }
    }
}