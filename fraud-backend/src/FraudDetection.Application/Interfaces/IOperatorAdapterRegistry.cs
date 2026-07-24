namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Port du registre de résolution d'adaptateurs opérateurs.
/// Centralise la RÈGLE DE PRIORITÉ que AnalyzeTransactionHandler ne doit pas
/// avoir à connaître : un adaptateur spécifique (IsFallback = false) est
/// toujours préféré à un adaptateur fallback (IsFallback = true) pour le
/// même code opérateur.
///
/// Sans ce registre, un Handler qui ferait lui-même
/// _adapters.FirstOrDefault(a => a.CanHandle(code)) risquerait de
/// sélectionner arbitrairement le fallback générique à la place d'un vrai
/// adaptateur dédié (ex: BankilyWebhookAdapter), selon l'ordre d'énumération
/// non garanti du conteneur DI.
/// </summary>
public interface IOperatorAdapterRegistry
{
    /// <summary>
    /// Résout l'adaptateur à utiliser pour un code opérateur donné.
    /// Retourne null si aucun adaptateur (ni spécifique, ni fallback)
    /// ne gère ce code — cas qui ne devrait jamais arriver tant qu'un
    /// fallback générique est enregistré, mais reste possible si celui-ci
    /// est volontairement retiré du DI en production.
    /// </summary>
    IOperatorWebhookAdapter? Resolve(string operatorCode);
}