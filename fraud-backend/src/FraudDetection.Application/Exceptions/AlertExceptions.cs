namespace FraudDetection.Application.Exceptions;

/// <summary>
/// Levée quand l'AlertId demandé n'existe pas en base — erreur CÔTÉ CLIENT
/// (ID invalide ou déjà supprimé), mappée vers 404 par GlobalExceptionMiddleware.
/// </summary>
public sealed class AlertNotFoundException : Exception
{
    public string AlertId { get; }

    public AlertNotFoundException(string alertId)
        : base($"Alerte {alertId} introuvable. Elle a peut-être été supprimée ou l'AlertId est incorrect.")
    {
        AlertId = alertId;
    }
}

/// <summary>
/// Levée quand un agent tente de confirmer/écarter une alerte déjà traitée
/// par un autre agent entre-temps — la ressource EXISTE mais son état
/// empêche l'action demandée. Mappée vers 409 Conflict (pas 404) par
/// GlobalExceptionMiddleware — sémantiquement correct : ce n'est pas
/// l'alerte qui est introuvable, c'est l'action qui n'est plus possible.
///
/// Enveloppe l'InvalidOperationException levée par Alert.Confirm()/Dismiss()
/// (Domain, EnsureCanBeReviewed) — le Domain reste la seule source de
/// vérité qui applique cette règle métier ; ValidateAlertHandler se
/// contente de traduire cet échec en un type exploitable par l'API.
/// </summary>
public sealed class AlertAlreadyProcessedException : Exception
{
    public string AlertId { get; }

    public AlertAlreadyProcessedException(string alertId, Exception innerException)
        : base(
            $"L'alerte {alertId} a déjà été traitée par un autre agent.",
            innerException)
    {
        AlertId = alertId;
    }
}