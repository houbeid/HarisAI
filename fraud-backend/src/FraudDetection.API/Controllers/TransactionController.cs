using FraudDetection.API.Middleware;
using FraudDetection.Application.Commands.AnalyzeTransaction;
using FraudDetection.Application.Interfaces;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace FraudDetection.API.Controllers;

/// <summary>
/// Réponse retournée à l'opérateur suite à un webhook — LE contrat .NET
/// définit lui-même vers l'opérateur (distinct de ScoreOut, le contrat
/// Python déjà figé vers .NET). Contient la décision synchrone attendue
/// par l'opérateur pour agir en temps réel sur la transaction.
/// </summary>
public sealed record WebhookResponse(
    string TransactionId,
    string Decision,
    int Score,
    bool IsProvisional);

/// <summary>
/// Reçoit les webhooks de transaction depuis les opérateurs mobile money.
/// Protégé exclusivement par le schéma "Hmac" — jamais "Jwt" (réservé aux
/// agents humains sur AlertController/ReportController).
///
/// RESPONSABILITÉ STRICTEMENT LIMITÉE : recevoir, construire la commande,
/// l'envoyer via MediatR, traduire le résultat en réponse HTTP. Aucune
/// logique métier ici — tout vit dans AnalyzeTransactionHandler.
///
/// GESTION D'ERREUR : aucun try/catch ici — ValidationException et
/// OperatorNotConfiguredException levées par MediatR/Handlers sont
/// interceptées par GlobalExceptionMiddleware (une seule source de vérité
/// pour toute l'API, voir ce fichier).
/// </summary>
[ApiController]
[Route("webhook")]
[Authorize(AuthenticationSchemes = "Hmac")]
public sealed class TransactionController : ControllerBase
{
    private readonly IMediator _mediator;

    public TransactionController(IMediator mediator)
    {
        _mediator = mediator;
    }

    [HttpPost]
    public async Task<IActionResult> ReceiveWebhook(CancellationToken cancellationToken)
    {
        // L'opérateur est lu depuis le principal AUTHENTIFIÉ (claim posé par
        // HmacAuthenticationHandler après validation cryptographique de la
        // signature) — jamais re-lu depuis le header brut à ce stade, pour
        // ne jamais faire confiance à une donnée non vérifiée après coup.
        var operatorCode = User.FindFirst("operator_code")?.Value;
        if (string.IsNullOrWhiteSpace(operatorCode))
        {
            // Ne devrait jamais arriver si [Authorize] a laissé passer la
            // requête — filet de sécurité, pas un cas métier normal.
            return Unauthorized();
        }

        // HmacAuthenticationHandler a déjà activé EnableBuffering() et remis
        // le curseur à zéro — cette lecture ne consomme pas le flux pour de bon.
        using var reader = new StreamReader(Request.Body);
        var rawBody = await reader.ReadToEndAsync(cancellationToken);

        var headers = Request.Headers.ToDictionary(
            h => h.Key, h => h.Value.ToString());

        var payload = new RawWebhookPayload(
            operatorCode: operatorCode,
            rawBody: rawBody,
            headers: headers,
            receivedAt: DateTimeOffset.UtcNow);

        var correlationId = HttpContext.GetCorrelationId();

        var command = new AnalyzeTransactionCommand(payload, correlationId);

        var result = await _mediator.Send(command, cancellationToken);

        var response = new WebhookResponse(
            TransactionId: result.TransactionId,
            Decision: result.Score.Decision.ToString().ToUpperInvariant(),
            Score: result.Score.Score,
            IsProvisional: result.IsDefaultReview);

        return Ok(response);
    }
}