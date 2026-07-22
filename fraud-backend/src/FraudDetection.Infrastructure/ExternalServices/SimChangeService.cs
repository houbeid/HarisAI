using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Infrastructure.ExternalServices;

/// <summary>
/// Implémentation de ISimChangeService.
///
/// RÔLE EXACT : enrichissement, pas détection. Calcule le FAIT BRUT
/// sim_changed_72h à transmettre à FastAPI — ne décide jamais de la fraude.
///
/// ÉTAT ACTUEL (point ouvert — doc technique section ⚠ point 3) :
///   La source réelle de cette donnée dépend du format webhook Bankily,
///   pas encore obtenu. Deux stratégies possibles une fois connu :
///     1. L'opérateur fournit directement sim_changed_72h dans son webhook
///        → l'adaptateur (BankilyWebhookAdapter) le positionne déjà correctement,
///          ce service devient un no-op de confirmation.
///     2. L'opérateur fournit seulement sim_changed_at (timestamp du dernier
///        changement de SIM) ou rien du tout → ce service doit interroger
///        une source télécom locale (table interne, API opérateur) pour
///        calculer si ce changement date de moins de 72h.
///
/// IMPLÉMENTATION ACTUELLE : heuristique basée sur sim_changed_at si présent
/// dans la Transaction adaptée. Si absent, retourne la transaction inchangée
/// (valeur false posée par défaut par l'adaptateur) — pas d'appel externe
/// tant que la source télécom réelle n'est pas identifiée.
/// </summary>
public sealed class SimChangeService : ISimChangeService
{
    private static readonly TimeSpan SimSwapWindow = TimeSpan.FromHours(72);

    private readonly ILogger<SimChangeService> _logger;

    public SimChangeService(ILogger<SimChangeService> logger)
    {
        _logger = logger;
    }

    public Task<Transaction> EnrichAsync(
        Transaction transaction,
        CancellationToken cancellationToken = default)
    {
        // Cas 1 : sim_changed_at est déjà renseigné par l'adaptateur —
        // recalcule sim_changed_72h à partir de ce timestamp plutôt que
        // de faire confiance à la valeur booléenne brute, qui peut être
        // obsolète si le webhook a transité avec un léger délai.
        if (transaction.SimChangedAt.HasValue)
        {
            var elapsed = transaction.Timestamp - transaction.SimChangedAt.Value;
            var recalculated = elapsed >= TimeSpan.Zero && elapsed <= SimSwapWindow;

            if (recalculated != transaction.SimChanged72h)
            {
                _logger.LogInformation(
                    "sim_changed_72h recalculé — TransactionId={TransactionId} " +
                    "Original={Original} Recalculé={Recalculated} SimChangedAt={SimChangedAt}",
                    transaction.TransactionId,
                    transaction.SimChanged72h,
                    recalculated,
                    transaction.SimChangedAt);
            }

            return Task.FromResult(
                transaction.WithSimChanged72h(recalculated, transaction.SimChangedAt));
        }

        // Cas 2 : aucune information de changement de SIM disponible.
        // L'adaptateur a positionné false par défaut — on ne peut pas
        // l'améliorer sans source télécom locale. Retourné tel quel.
        //
        // POINT OUVERT : une fois la source télécom identifiée (webhook
        // Bankily réel ou API interne opérateur), remplacer ce bloc par
        // un appel réel à cette source.
        _logger.LogDebug(
            "sim_changed_72h non calculable — aucune source disponible pour " +
            "TransactionId={TransactionId}. Valeur par défaut (false) conservée.",
            transaction.TransactionId);

        return Task.FromResult(transaction);
    }
}