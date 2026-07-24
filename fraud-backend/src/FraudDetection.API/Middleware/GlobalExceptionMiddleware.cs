using System.Text.Json;
using FluentValidation;
using FraudDetection.Application.Exceptions;

namespace FraudDetection.API.Middleware;

/// <summary>
/// Traduit centralement les exceptions levées par les Handlers Application
/// en réponses HTTP JSON — UNE SEULE fois pour toute l'application, plutôt
/// que dupliqué dans un try/catch par Controller (TransactionController,
/// AlertController, ReportController avaient chacun leur propre traduction
/// avant ce middleware).
///
/// MAPPING EXPLICITE PAR TYPE, JAMAIS PAR INSPECTION DE MESSAGE :
///   ValidationException (FluentValidation)   → 400 Bad Request
///   OperatorNotConfiguredException            → 500 Internal Server Error
///   AlertNotFoundException                     → 404 Not Found
///   AlertAlreadyProcessedException             → 409 Conflict
///   Toute autre exception non prévue           → 500, message générique
///     (ne jamais exposer ex.Message d'une exception inattendue au client —
///      risque de fuite d'information interne ; le détail va dans les logs)
///
/// DOIT ÊTRE ENREGISTRÉ TÔT DANS LE PIPELINE (avant les Controllers,
/// idéalement juste après CorrelationIdMiddleware) pour intercepter
/// toute exception venant de MediatR/Handlers.
/// </summary>
public sealed class GlobalExceptionMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<GlobalExceptionMiddleware> _logger;

    public GlobalExceptionMiddleware(
        RequestDelegate next,
        ILogger<GlobalExceptionMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (ValidationException ex)
        {
            await WriteResponseAsync(
                context,
                StatusCodes.Status400BadRequest,
                error: "invalid_payload",
                details: ex.Errors.Select(e => e.ErrorMessage));

            _logger.LogWarning(
                "Requête rejetée — validation échouée : {Errors}",
                string.Join("; ", ex.Errors.Select(e => e.ErrorMessage)));
        }
        catch (OperatorNotConfiguredException ex)
        {
            await WriteResponseAsync(
                context,
                StatusCodes.Status500InternalServerError,
                error: "operator_not_configured",
                details: new[] { ex.Message });

            // Error, pas Warning — c'est une erreur de configuration serveur
            // (DI incomplet), pas une erreur normale de l'appelant.
            _logger.LogError(ex,
                "Opérateur non configuré — OperatorCode={OperatorCode}",
                ex.OperatorCode);
        }
        catch (AlertNotFoundException ex)
        {
            await WriteResponseAsync(
                context,
                StatusCodes.Status404NotFound,
                error: "alert_not_found",
                details: new[] { ex.Message });

            _logger.LogWarning(
                "Alerte introuvable — AlertId={AlertId}", ex.AlertId);
        }
        catch (AlertAlreadyProcessedException ex)
        {
            await WriteResponseAsync(
                context,
                StatusCodes.Status409Conflict,
                error: "alert_already_processed",
                details: new[] { ex.Message });

            _logger.LogWarning(
                "Conflit — alerte déjà traitée — AlertId={AlertId}", ex.AlertId);
        }
        catch (Exception ex)
        {
            // Filet de sécurité — toute exception non prévue. Ne JAMAIS
            // exposer ex.Message au client ici : risque de fuite d'un
            // détail interne (chaîne de connexion, chemin de fichier, etc.).
            // Le détail complet va dans les logs serveur uniquement.
            await WriteResponseAsync(
                context,
                StatusCodes.Status500InternalServerError,
                error: "internal_server_error",
                details: null);

            _logger.LogError(ex,
                "Exception non gérée — {ExceptionType}: {Message}",
                ex.GetType().Name, ex.Message);
        }
    }

    private static Task WriteResponseAsync(
        HttpContext context,
        int statusCode,
        string error,
        IEnumerable<string>? details)
    {
        context.Response.StatusCode = statusCode;
        context.Response.ContentType = "application/json";

        var payload = new { error, details };

        return context.Response.WriteAsync(JsonSerializer.Serialize(payload));
    }
}