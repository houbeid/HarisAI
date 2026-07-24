namespace FraudDetection.Application.Exceptions;

/// <summary>
/// Levée quand aucun adaptateur (spécifique ou fallback) n'est enregistré
/// pour l'opérateur d'un webhook reçu — erreur de CONFIGURATION SERVEUR,
/// jamais une erreur causée par l'appelant. Mappée vers 500 par
/// GlobalExceptionMiddleware.
///
/// Distincte de AlertNotFoundException / AlertAlreadyProcessedException,
/// qui elles sont des erreurs côté client (4xx) — cette séparation de
/// types est ce qui permet à un middleware générique de choisir le bon
/// code HTTP sans inspecter le message de l'exception.
/// </summary>
public sealed class OperatorNotConfiguredException : Exception
{
    public string OperatorCode { get; }

    public OperatorNotConfiguredException(string operatorCode)
        : base(
            $"Opérateur non supporté : {operatorCode}. " +
            $"Ajouter un adaptateur IOperatorWebhookAdapter et l'enregistrer dans le DI.")
    {
        OperatorCode = operatorCode;
    }
}