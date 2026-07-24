using FraudDetection.Application.Interfaces;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Infrastructure.Adapters;

/// <summary>
/// Implémentation de IOperatorAdapterRegistry.
/// Reçoit tous les IOperatorWebhookAdapter enregistrés dans le DI
/// (voir Program.cs) et applique la règle de priorité à la résolution :
///
///   1. Chercher d'abord parmi les adaptateurs SPÉCIFIQUES (IsFallback = false)
///      celui qui répond CanHandle(operatorCode) = true
///   2. Si aucun ne correspond, chercher parmi les FALLBACKS (IsFallback = true)
///
/// AJOUTER UN NOUVEL OPÉRATEUR (ex: vrai format Bankily une fois l'accord signé) :
///   Créer une classe implémentant IOperatorWebhookAdapter (IsFallback reste
///   à sa valeur par défaut false), l'enregistrer dans le DI — CanHandle()
///   ciblera précisément ce code. Aucune modification de ce registre,
///   ni de GenericMobileMoneyWebhookAdapter, n'est nécessaire.
/// </summary>
public sealed class OperatorAdapterRegistry : IOperatorAdapterRegistry
{
    private readonly IReadOnlyList<IOperatorWebhookAdapter> _adapters;
    private readonly ILogger<OperatorAdapterRegistry> _logger;

    public OperatorAdapterRegistry(
        IEnumerable<IOperatorWebhookAdapter> adapters,
        ILogger<OperatorAdapterRegistry> logger)
    {
        _adapters = adapters.ToList();
        _logger = logger;

        if (_adapters.Count == 0)
        {
            _logger.LogWarning(
                "Aucun IOperatorWebhookAdapter enregistré dans le DI — " +
                "aucun webhook opérateur ne pourra être traité.");
        }
    }

    public IOperatorWebhookAdapter? Resolve(string operatorCode)
    {
        // Étape 1 — priorité aux adaptateurs spécifiques
        var specific = _adapters
            .Where(a => !a.IsFallback)
            .FirstOrDefault(a => a.CanHandle(operatorCode));

        if (specific is not null)
        {
            _logger.LogDebug(
                "Adaptateur spécifique résolu pour {OperatorCode} : {AdapterType}",
                operatorCode, specific.GetType().Name);
            return specific;
        }

        // Étape 2 — repli sur un adaptateur fallback
        var fallback = _adapters
            .Where(a => a.IsFallback)
            .FirstOrDefault(a => a.CanHandle(operatorCode));

        if (fallback is not null)
        {
            _logger.LogInformation(
                "Aucun adaptateur spécifique pour {OperatorCode} — " +
                "utilisation du fallback {AdapterType}. Créer un adaptateur dédié " +
                "dès qu'un accord formel avec cet opérateur est signé.",
                operatorCode, fallback.GetType().Name);
            return fallback;
        }

        _logger.LogError(
            "Aucun adaptateur (spécifique ou fallback) ne gère l'opérateur {OperatorCode}.",
            operatorCode);
        return null;
    }
}