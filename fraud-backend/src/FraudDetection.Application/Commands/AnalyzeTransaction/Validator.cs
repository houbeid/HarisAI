using FluentValidation;

namespace FraudDetection.Application.Commands.AnalyzeTransaction;

/// <summary>
/// Valide la structure de AnalyzeTransactionCommand avant que le Handler
/// ne soit exécuté. Enregistré automatiquement par MediatR + FluentValidation
/// via le pipeline behavior ValidationBehavior (à configurer dans Program.cs).
///
/// DEUX NIVEAUX DE VALIDATION DISTINCTS :
///
/// 1. Ce Validator — validation STRUCTURELLE :
///    Champs présents, non vides, formats cohérents.
///    Retourne 400 Bad Request si la structure est invalide.
///    S'exécute AVANT le Handler — pas d'accès aux dépendances métier.
///
/// 2. Le Handler — validation MÉTIER :
///    L'opérateur a-t-il un adaptateur enregistré ?
///    La transaction est-elle déjà connue (doublon) ?
///    Ces vérifications nécessitent les repositories et le registre —
///    elles appartiennent au Handler, pas au Validator.
/// </summary>
public sealed class AnalyzeTransactionCommandValidator
    : AbstractValidator<AnalyzeTransactionCommand>
{
    public AnalyzeTransactionCommandValidator()
    {
        // ── CorrelationId ────────────────────────────────────────────
        RuleFor(x => x.CorrelationId)
            .NotEmpty()
            .WithMessage("CorrelationId est obligatoire.")
            .MaximumLength(100)
            .WithMessage("CorrelationId ne peut pas dépasser 100 caractères.");

        // ── Payload ─────────────────────────────────────────────────
        RuleFor(x => x.Payload)
            .NotNull()
            .WithMessage("Le payload webhook ne peut pas être null.");

        // ── OperatorCode ─────────────────────────────────────────────
        // Validation structurelle uniquement — on vérifie que le code
        // est présent et alphanumérique. La vérification qu'un adaptateur
        // existe pour cet opérateur appartient au Handler (validation métier).
        RuleFor(x => x.Payload.OperatorCode)
            .NotEmpty()
            .WithMessage("Le code opérateur est obligatoire.")
            .MaximumLength(50)
            .WithMessage("Le code opérateur ne peut pas dépasser 50 caractères.")
            .Matches(@"^[A-Z0-9_]+$")
            .WithMessage(
                "Le code opérateur doit être en majuscules, chiffres ou underscores uniquement. " +
                "Exemples valides : BANKILY, SEDAD, MASRVI.");

        // ── RawBody ──────────────────────────────────────────────────
        RuleFor(x => x.Payload.RawBody)
            .NotEmpty()
            .WithMessage("Le corps du webhook ne peut pas être vide.")
            .MaximumLength(64_000)
            .WithMessage("Le corps du webhook dépasse la taille maximale autorisée (64 Ko).")
            .Must(BeValidJson)
            .WithMessage("Le corps du webhook doit être un JSON valide.");

        // ── ReceivedAt ───────────────────────────────────────────────
        // Un webhook trop ancien (> 5 minutes) indique soit un problème réseau
        // grave, soit une tentative de replay. La validation HMAC (timestamp)
        // dans HmacAuthenticationHandler bloque déjà les replays — cette règle
        // est une garde supplémentaire côté métier.
        RuleFor(x => x.Payload.ReceivedAt)
            .Must(BeRecent)
            .WithMessage(
                "Le webhook est trop ancien (plus de 5 minutes). " +
                "Vérifier la synchronisation horaire entre l'opérateur et le serveur.");
    }

    private static bool BeValidJson(string rawBody)
    {
        if (string.IsNullOrWhiteSpace(rawBody))
            return false;

        try
        {
            System.Text.Json.JsonDocument.Parse(rawBody);
            return true;
        }
        catch (System.Text.Json.JsonException)
        {
            return false;
        }
    }

    private static bool BeRecent(DateTimeOffset receivedAt)
    {
        var age = DateTimeOffset.UtcNow - receivedAt;
        return age.TotalMinutes <= 5;
    }
}