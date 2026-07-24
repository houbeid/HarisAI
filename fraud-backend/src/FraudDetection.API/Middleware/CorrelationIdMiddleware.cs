using Serilog.Context;

namespace FraudDetection.API.Middleware;

/// <summary>
/// Génère (ou réutilise) un identifiant de corrélation pour chaque requête,
/// et le propage à trois endroits :
///   1. HttpContext.Items["CorrelationId"] — lisible par les Controllers
///   2. Header de réponse X-Correlation-Id — visible côté opérateur/client
///   3. Contexte Serilog (LogContext.PushProperty) — TOUS les logs émis
///      pendant cette requête incluent automatiquement le CorrelationId,
///      sans qu'aucun appel de log individuel n'ait à le préciser
///
/// COMBLE LE MANQUE DÉJÀ DOCUMENTÉ CÔTÉ PYTHON (section 10.2 de la doc
/// technique) : "pas de correlation ID inter-services — impossible de
/// tracer une transaction de bout en bout entre .NET et FastAPI". Ce
/// middleware est la moitié .NET de cette correction — le CorrelationId
/// est aussi transmis en header HTTP vers FastAPI par MlScoringService
/// (à câbler séparément — voir note dans ce fichier).
///
/// DOIT ÊTRE ENREGISTRÉ TRÈS TÔT DANS LE PIPELINE (avant UseAuthentication,
/// UseRouting) — pour que même les requêtes rejetées par l'authentification
/// (401/403) aient un CorrelationId dans leurs logs.
/// </summary>
public sealed class CorrelationIdMiddleware
{
    public const string HeaderName = "X-Correlation-Id";
    public const string HttpContextItemKey = "CorrelationId";

    private readonly RequestDelegate _next;

    public CorrelationIdMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var correlationId = ResolveCorrelationId(context);

        context.Items[HttpContextItemKey] = correlationId;

        context.Response.OnStarting(() =>
        {
            context.Response.Headers[HeaderName] = correlationId;
            return Task.CompletedTask;
        });

        // Toute ligne de log émise par n'importe quel composant pendant
        // le traitement de cette requête (Handler, Repository, MlScoringService,
        // HmacAuthenticationHandler, etc.) inclut automatiquement CorrelationId
        // sans modification de leur code — c'est l'intérêt de LogContext.
        using (LogContext.PushProperty("CorrelationId", correlationId))
        {
            await _next(context);
        }
    }

    /// <summary>
    /// Réutilise le header entrant s'il existe déjà (utile si un proxy ou
    /// un futur système d'API Gateway propage son propre identifiant),
    /// sinon en génère un nouveau. Ne fait jamais confiance à un
    /// CorrelationId entrant vide ou manifestement invalide.
    /// </summary>
    private static string ResolveCorrelationId(HttpContext context)
    {
        if (context.Request.Headers.TryGetValue(HeaderName, out var existing)
            && !string.IsNullOrWhiteSpace(existing))
        {
            return existing.ToString();
        }

        return Guid.NewGuid().ToString();
    }
}

/// <summary>
/// Méthode d'extension pour lire le CorrelationId depuis un HttpContext —
/// évite que chaque Controller ré-écrive la même clé de dictionnaire.
/// </summary>
public static class HttpContextCorrelationIdExtensions
{
    public static string GetCorrelationId(this HttpContext context) =>
        context.Items[CorrelationIdMiddleware.HttpContextItemKey] as string
        ?? context.TraceIdentifier; // filet de sécurité si le middleware n'était pas enregistré
}