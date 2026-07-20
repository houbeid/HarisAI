using FraudDetection.Domain.Entities;

namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Port d'enrichissement de la feature sim_changed_72h.
/// Calcule si la SIM du client a changé dans les 72h précédant la transaction,
/// et retourne une Transaction enrichie avec la valeur correcte.
///
/// RÔLE EXACT : enrichissement, pas détection.
/// Ce service calcule un FAIT BRUT (la SIM a-t-elle changé ?)
/// à transmettre à FastAPI comme feature d'entrée.
/// La décision de fraude reste exclusivement dans XGBoost côté Python,
/// où sim_changed_72h est la 4e feature la plus importante (8.58% de gain).
///
/// DEUX CAS D'USAGE :
///
/// Cas 1 — L'opérateur fournit sim_changed_72h dans son webhook :
///   L'adaptateur (BankilyWebhookAdapter) extrait et positionne
///   la valeur directement. EnrichAsync détecte que la valeur est
///   déjà correcte et retourne la transaction inchangée (no-op).
///
/// Cas 2 — L'opérateur ne fournit pas sim_changed_72h :
///   L'adaptateur positionne false par défaut.
///   EnrichAsync calcule la valeur réelle depuis la source disponible
///   sur ce site (table télécom interne, API opérateur, etc.)
///   et retourne une nouvelle Transaction avec la valeur corrigée.
///
/// POINT OUVERT (doc technique section ⚠ point 3) :
///   La source réelle de cette donnée dépend du format webhook Bankily,
///   pas encore obtenu. L'implémentation concrète (SimChangeService.cs)
///   sera ajustée une fois ce format connu.
///   En attendant, SimChangeService peut implémenter une heuristique
///   basée sur sim_changed_at si le timestamp est fourni dans le webhook.
///
/// NOTE SUR Transaction.cs :
///   Pour retourner une Transaction enrichie, l'implémentation utilise
///   Transaction.WithSimChanged72h(bool) — méthode à ajouter dans
///   Transaction.cs (retourne une nouvelle instance avec la valeur corrigée,
///   tous les autres champs inchangés).
/// </summary>
public interface ISimChangeService
{
    /// <summary>
    /// Enrichit la transaction avec la valeur correcte de sim_changed_72h.
    /// Retourne toujours une Transaction valide — jamais null, jamais d'exception
    /// sur l'indisponibilité d'une source de données télécom :
    /// en cas d'échec de calcul, retourne la transaction avec la valeur
    /// fournie par l'adaptateur (false par défaut) plutôt que de bloquer
    /// le pipeline de détection.
    /// </summary>
    Task<Transaction> EnrichAsync(
        Transaction transaction,
        CancellationToken cancellationToken = default);
}