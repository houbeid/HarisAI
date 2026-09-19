using FraudDetection.Application.Commands.CreateAlert;
using FraudDetection.Application.Exceptions;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Commands.AnalyzeTransaction;

/// <summary>
/// Orchestrateur principal du pipeline de détection de fraude côté .NET.
///
/// FLUX D'EXÉCUTION (dans l'ordre) :
///   1. Sélectionner l'adaptateur opérateur via le registre
///   2. Transformer RawWebhookPayload → Transaction (domaine)
///   3. Détecter les doublons (retry Bankily) — réponse idempotente
///   4. Persister le webhook reçu (avant appel ML — trace même si FastAPI down)
///   5. Enrichir sim_changed_72h via ISimChangeService si absent du webhook
///   6. Appeler fraud-ml-service (FastAPI) via IMlScoringService
///   7. Mettre à jour la transaction avec le score reçu
///   8. Si FastAPI indisponible → enqueue pour rescoring ultérieur
///   9. Si REVIEW ou BLOCK → déclencher CreateAlertCommand
///  10. Retourner AnalyzeTransactionResult au Controller
///
/// CE QUE CE HANDLER NE FAIT PAS :
///   - Valider la signature HMAC (HmacAuthenticationHandler, avant MediatR)
///   - Calculer le score de fraude (FastAPI via IMlScoringService)
///   - Persister dans ml_audit (PostgresAuditStore, côté Python)
///   - Notifier l'opérateur du résultat (TransactionController, après ce handler)
/// </summary>
public sealed class AnalyzeTransactionHandler
    : IRequestHandler<AnalyzeTransactionCommand, AnalyzeTransactionResult>
{
    private readonly IOperatorAdapterRegistry _adapterRegistry;
    private readonly IMlScoringService _mlScoringService;
    private readonly ISimChangeService _simChangeService;
    private readonly ITransactionRepository _transactionRepository;
    private readonly IPendingTransactionQueue _pendingQueue;
    private readonly IMediator _mediator;
    private readonly ILogger<AnalyzeTransactionHandler> _logger;

    public AnalyzeTransactionHandler(
        IOperatorAdapterRegistry adapterRegistry,
        IMlScoringService mlScoringService,
        ISimChangeService simChangeService,
        ITransactionRepository transactionRepository,
        IPendingTransactionQueue pendingQueue,
        IMediator mediator,
        ILogger<AnalyzeTransactionHandler> logger)
    {
        _adapterRegistry = adapterRegistry;
        _mlScoringService = mlScoringService;
        _simChangeService = simChangeService;
        _transactionRepository = transactionRepository;
        _pendingQueue = pendingQueue;
        _mediator = mediator;
        _logger = logger;
    }

    public async Task<AnalyzeTransactionResult> Handle(
        AnalyzeTransactionCommand request,
        CancellationToken cancellationToken)
    {
        var operatorCode = request.Payload.OperatorCode;

        // ── Étape 1 : Sélectionner l'adaptateur via le registre ───────────────
        // Le registre applique la priorité spécifique > fallback — ce Handler
        // n'a pas à connaître cette règle (voir IOperatorAdapterRegistry).
        var adapter = _adapterRegistry.Resolve(operatorCode);
        if (adapter is null)
        {
            _logger.LogError(
                "Aucun adaptateur enregistré pour l'opérateur {OperatorCode}. " +
                "Vérifier l'enregistrement DI dans Program.cs.",
                operatorCode);

            throw new OperatorNotConfiguredException(operatorCode);
        }

        // ── Étape 2 : Transformer le payload brut → Transaction ───────────────
        Transaction transaction;
        try
        {
            transaction = adapter.Adapt(request.Payload);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "Échec de l'adaptation du webhook {OperatorCode}. " +
                "Payload malformé ou format inconnu.",
                operatorCode);
            throw;
        }

        _logger.LogInformation(
            "Webhook reçu — TransactionId={TransactionId} Operator={Operator} " +
            "Amount={Amount} Channel={Channel} CorrelationId={CorrelationId}",
            transaction.TransactionId,
            transaction.Operator,
            transaction.Amount,
            transaction.Channel,
            request.CorrelationId);

        // ── Étape 3 : Détecter les doublons (retry opérateur) ─────────────────
        // L'idempotence côté ML (même transaction_id dans les 5 min) est déjà
        // gérée par PredictionCache côté FastAPI. Côté .NET, on évite juste
        // de sauvegarder deux fois la même transaction dans fraud_backend.
        var existing = await _transactionRepository.GetByIdAsync(
            transaction.TransactionId, cancellationToken);

        if (existing is not null)
        {
            _logger.LogWarning(
                "Transaction dupliquée détectée — TransactionId={TransactionId}. " +
                "Retry opérateur probable. Appel ML tout de même (cache FastAPI actif).",
                transaction.TransactionId);
        }

        // ── Étape 4 : Persister le webhook reçu ───────────────────────────────
        // AVANT l'appel ML — garantit une trace même si FastAPI est indisponible
        // et que le pod .NET redémarre entre temps.
        if (existing is null)
        {
            await _transactionRepository.SaveAsync(transaction, cancellationToken);
        }

        // ── Étape 5 : Enrichir sim_changed_72h ────────────────────────────────
        // L'adaptateur positionne sim_changed_72h à false par défaut si absent
        // du webhook Bankily. ISimChangeService calcule la valeur réelle depuis
        // la source de données télécom disponible sur ce site.
        // Si la valeur est déjà correcte (opérateur la fournit dans son webhook),
        // ComputeAsync retourne la même valeur sans effet de bord.
        var enrichedTransaction = await _simChangeService.EnrichAsync(
            transaction, cancellationToken);

        // ── Étape 6 : Appeler fraud-ml-service ────────────────────────────────
        // IMlScoringService ne lève jamais d'exception sur une panne FastAPI —
        // Polly retourne RiskScore.DefaultReview() (FraudType="UNAVAILABLE").
        var score = await _mlScoringService.AnalyzeAsync(
            enrichedTransaction, request.CorrelationId, cancellationToken);

        bool isDefaultReview = score.FraudType == "UNAVAILABLE";

        if (isDefaultReview)
        {
            _logger.LogWarning(
                "fraud-ml-service indisponible — décision par défaut REVIEW appliquée " +
                "pour TransactionId={TransactionId}. Transaction mise en file de rescoring.",
                transaction.TransactionId);
        }
        else
        {
            _logger.LogInformation(
                "Score reçu — TransactionId={TransactionId} Decision={Decision} " +
                "Score={Score} FraudType={FraudType} InferenceMs={InferenceMs}",
                transaction.TransactionId,
                score.Decision,
                score.Score,
                score.FraudType,
                score.InferenceTimeMs);
        }

        // ── Étape 7 : Mettre à jour le score en base ──────────────────────────
        await _transactionRepository.UpdateScoreAsync(
            transaction.TransactionId, score, cancellationToken);

        // ── Étape 8 : Enqueue si FastAPI était indisponible ───────────────────
        // PendingTransactionWorker relancera le scoring dès que /health répond.
        // La décision finale APPROVE/REVIEW/BLOCK réelle viendra mettre à jour
        // l'audit trail après coup.
        if (isDefaultReview)
        {
            await _pendingQueue.EnqueueAsync(enrichedTransaction, cancellationToken);
        }

        // ── Étape 9 : Créer une alerte si REVIEW ou BLOCK ────────────────────
        // AlertId est présent dans ScoreOut uniquement pour REVIEW et BLOCK
        // (contrat FastAPI figé — section 9.2 de la doc technique).
        if (score.RequiresHumanReview && score.AlertId is not null)
        {
            await _mediator.Send(
                new CreateAlertCommand(
                    alertId: score.AlertId,
                    transactionId: transaction.TransactionId,
                    operatorCode: transaction.Operator,
                    score: score,
                    amount: enrichedTransaction.Amount),
                cancellationToken);
        }

        // ── Étape 10 : Retourner le résultat au Controller ────────────────────
        return new AnalyzeTransactionResult(
            transactionId: transaction.TransactionId,
            score: score,
            isDefaultReview: isDefaultReview);
    }
}