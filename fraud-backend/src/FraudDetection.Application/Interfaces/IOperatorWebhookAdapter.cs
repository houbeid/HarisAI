using FraudDetection.Domain.Entities;

namespace FraudDetection.Application.Interfaces;

/// <summary>
/// Représente le payload brut reçu depuis un opérateur mobile money
/// avant toute transformation vers le domaine.
///
/// Le format exact de ce payload est inconnu pour l'instant (Bankily n'a pas
/// encore fourni sa documentation webhook). RawWebhookPayload encapsule ce
/// contenu brut avec ses métadonnées pour que l'adaptateur puisse en extraire
/// ce dont il a besoin, quel que soit le format réel.
/// </summary>
public sealed record RawWebhookPayload
{
    /// <summary>
    /// Code opérateur extrait du header ou de la route HTTP — ex: "BANKILY".
    /// Utilisé par OperatorAdapterRegistry pour sélectionner le bon adaptateur
    /// avant même de lire le corps de la requête.
    /// </summary>
    public string OperatorCode { get; }

    /// <summary>
    /// Corps brut de la requête HTTP en JSON.
    /// L'adaptateur est responsable de le désérialiser selon le format
    /// propre à chaque opérateur.
    /// </summary>
    public string RawBody { get; }

    /// <summary>
    /// Headers HTTP de la requête — nécessaires pour la validation HMAC
    /// (X-Signature, X-Timestamp) dans HmacAuthenticationHandler.
    /// Transmis ici pour que l'adaptateur puisse les lire si besoin.
    /// </summary>
    public IReadOnlyDictionary<string, string> Headers { get; }

    /// <summary>Horodatage de réception côté .NET — pour le log d'audit local.</summary>
    public DateTimeOffset ReceivedAt { get; }

    public RawWebhookPayload(
        string operatorCode,
        string rawBody,
        IReadOnlyDictionary<string, string> headers,
        DateTimeOffset receivedAt)
    {
        if (string.IsNullOrWhiteSpace(operatorCode))
            throw new ArgumentException("OperatorCode ne peut pas être vide.", nameof(operatorCode));

        if (string.IsNullOrWhiteSpace(rawBody))
            throw new ArgumentException("RawBody ne peut pas être vide.", nameof(rawBody));

        ArgumentNullException.ThrowIfNull(headers);

        OperatorCode = operatorCode.Trim().ToUpperInvariant();
        RawBody = rawBody;
        Headers = headers;
        ReceivedAt = receivedAt;
    }
}

/// <summary>
/// Port du registre d'adaptateurs opérateurs.
/// Chaque opérateur mobile money (Bankily, Sedad, Masrvi, et tout futur opérateur
/// mauritanien ou africain) implémente cette interface pour transformer son format
/// de webhook propriétaire vers la Transaction du domaine.
///
/// PRINCIPE OUVERT/FERMÉ : ajouter un nouvel opérateur = créer une nouvelle classe
/// qui implémente cette interface + l'enregistrer dans le DI.
/// Aucun fichier existant (Domain, Application, Controllers) n'est modifié.
///
/// RESPONSABILITÉS DE L'ADAPTATEUR :
///   1. Transformer le payload brut → Transaction domaine
///   2. Anonymiser les données personnelles (numéro de téléphone → TokenHash)
///      AVANT que la Transaction soit construite — la PII ne doit jamais
///      atteindre le domaine ni FastAPI
///   3. Mapper le canal propriétaire de l'opérateur → Channel enum
///
/// CE QUE L'ADAPTATEUR NE FAIT PAS :
///   - Valider la signature HMAC (c'est HmacAuthenticationHandler)
///   - Calculer sim_changed_72h (c'est SimChangeService — enrichissement
///     fait dans AnalyzeTransactionHandler après l'adaptation)
///   - Décider de la fraude (c'est FastAPI via IMlScoringService)
/// </summary>
public interface IOperatorWebhookAdapter
{
    /// <summary>
    /// Indique si cet adaptateur prend en charge le code opérateur donné.
    /// Utilisé par OperatorAdapterRegistry pour sélectionner l'adaptateur actif.
    /// Exemple : BankilyWebhookAdapter.CanHandle("BANKILY") → true
    ///           BankilyWebhookAdapter.CanHandle("SEDAD")   → false
    /// </summary>
    bool CanHandle(string operatorCode);

    /// <summary>
    /// Transforme le payload brut de l'opérateur en Transaction du domaine.
    /// Lève une exception si le payload est malformé ou incomplet —
    /// la gestion de cette exception appartient au TransactionController,
    /// qui retournera un 400 Bad Request à l'opérateur.
    ///
    /// Note sur sim_changed_72h : si l'information n'est pas disponible
    /// dans le webhook de l'opérateur, l'adaptateur positionne la valeur
    /// à false par défaut. SimChangeService (appelé dans le handler) calculera
    /// la valeur réelle avant l'appel à FastAPI.
    /// </summary>
    Transaction Adapt(RawWebhookPayload payload);
}