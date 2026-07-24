using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace FraudDetection.Infrastructure.Auth;

/// <summary>
/// Handler d'authentification HMAC pour les webhooks opérateurs.
/// Protège exclusivement TransactionController — jamais AlertController
/// ni ReportController, qui utilisent JwtAuthenticationHandler pour les
/// agents de conformité humains.
///
/// SCHÉMA DE SIGNATURE (pattern Stripe/GitHub) :
///   payload_signé = "{timestamp}.{corps_de_la_requête}"
///   signature = HMAC-SHA256(payload_signé, secret_opérateur)
///   Header X-Signature attendu : "sha256=&lt;hex_digest&gt;" (préfixe optionnel)
///
/// Inclure le timestamp DANS le payload signé (pas seulement le comparer
/// séparément) empêche un attaquant de rejouer une requête légitime en
/// changeant juste le header X-Timestamp — le timestamp fait partie de
/// ce qui est cryptographiquement protégé.
///
/// PRÉREQUIS PROGRAM.CS : Request.EnableBuffering() est appelé directement
/// ici par sécurité, mais il est recommandé de l'activer aussi en amont
/// dans le pipeline (avant UseAuthentication) si d'autres middlewares
/// doivent aussi lire le corps de la requête.
///
/// CE QUE CE HANDLER NE FAIT PAS :
///   - Sélectionner l'adaptateur opérateur (IOperatorAdapterRegistry, Application)
///   - Désérialiser le payload métier (IOperatorWebhookAdapter.Adapt())
///   - Décider de la fraude (FastAPI)
/// </summary>
public sealed class HmacAuthenticationHandler : AuthenticationHandler<HmacAuthenticationOptions>
{
    private readonly IOperatorSecretProvider _secretProvider;

    public HmacAuthenticationHandler(
        IOptionsMonitor<HmacAuthenticationOptions> options,
        ILoggerFactory logger,
        UrlEncoder encoder,
        IOperatorSecretProvider secretProvider)
        : base(options, logger, encoder)
    {
        _secretProvider = secretProvider;
    }

    protected override async Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        // ── Étape 1 : Extraire les headers requis ─────────────────────────────
        if (!Request.Headers.TryGetValue(Options.OperatorHeaderName, out var operatorCodeValues)
            || string.IsNullOrWhiteSpace(operatorCodeValues.ToString()))
        {
            Logger.LogWarning(
                "Webhook rejeté — header {HeaderName} manquant.",
                Options.OperatorHeaderName);
            return AuthenticateResult.Fail("Code opérateur manquant.");
        }

        if (!Request.Headers.TryGetValue(Options.SignatureHeaderName, out var signatureValues)
            || string.IsNullOrWhiteSpace(signatureValues.ToString()))
        {
            Logger.LogWarning(
                "Webhook rejeté — header {HeaderName} manquant. Operator={OperatorCode}",
                Options.SignatureHeaderName, operatorCodeValues.ToString());
            return AuthenticateResult.Fail("Signature manquante.");
        }

        if (!Request.Headers.TryGetValue(Options.TimestampHeaderName, out var timestampValues)
            || !long.TryParse(timestampValues.ToString(), out var timestampUnix))
        {
            Logger.LogWarning(
                "Webhook rejeté — header {HeaderName} manquant ou invalide. Operator={OperatorCode}",
                Options.TimestampHeaderName, operatorCodeValues.ToString());
            return AuthenticateResult.Fail("Timestamp manquant ou invalide.");
        }

        var operatorCode = operatorCodeValues.ToString().Trim().ToUpperInvariant();

        // ── Étape 2 : Protection anti-replay — fraîcheur du timestamp ─────────
        var signedAt = DateTimeOffset.FromUnixTimeSeconds(timestampUnix);
        var age = DateTimeOffset.UtcNow - signedAt;

        if (age < TimeSpan.Zero || age > Options.ReplayWindow)
        {
            Logger.LogWarning(
                "Webhook rejeté — timestamp hors fenêtre acceptable ({Age} écoulées, " +
                "fenêtre {Window}). Operator={OperatorCode}. Possible replay ou horloge désynchronisée.",
                age, Options.ReplayWindow, operatorCode);
            return AuthenticateResult.Fail("Timestamp hors fenêtre acceptable.");
        }

        // ── Étape 3 : Récupérer le secret de l'opérateur ──────────────────────
        var secret = _secretProvider.GetSecret(operatorCode);
        if (secret is null)
        {
            // OperatorSecretProvider a déjà loggé le détail (LogError) —
            // ici on log juste le rejet côté authentification, pas de duplication.
            Logger.LogWarning(
                "Webhook rejeté — aucun secret configuré pour l'opérateur {OperatorCode}.",
                operatorCode);
            return AuthenticateResult.Fail("Opérateur non autorisé.");
        }

        // ── Étape 4 : Lire le corps brut de la requête ────────────────────────
        var rawBody = await ReadRawBodyAsync();

        // ── Étape 5 : Recalculer la signature attendue ────────────────────────
        var signedPayload = $"{timestampUnix}.{rawBody}";
        var expectedSignature = ComputeHmacSha256(signedPayload, secret);
        var providedSignature = NormalizeSignature(signatureValues.ToString());

        if (!ConstantTimeEquals(expectedSignature, providedSignature))
        {
            Logger.LogWarning(
                "Webhook rejeté — signature HMAC invalide. Operator={OperatorCode}. " +
                "Vérifier que le secret est correctement synchronisé avec l'opérateur.",
                operatorCode);
            return AuthenticateResult.Fail("Signature invalide.");
        }

        // ── Étape 6 : Authentification réussie — construire le principal ──────
        Logger.LogDebug(
            "Webhook authentifié avec succès — Operator={OperatorCode}",
            operatorCode);

        var claims = new[]
        {
            new Claim(ClaimTypes.Name, operatorCode),
            new Claim("operator_code", operatorCode)
        };
        var identity = new ClaimsIdentity(claims, Scheme.Name);
        var principal = new ClaimsPrincipal(identity);
        var ticket = new AuthenticationTicket(principal, Scheme.Name);

        return AuthenticateResult.Success(ticket);
    }

    /// <summary>
    /// Lit le corps de la requête sans le consommer définitivement —
    /// EnableBuffering() permet de relire le flux plus tard (le Controller
    /// et MediatR en auront besoin pour construire RawWebhookPayload.RawBody).
    /// </summary>
    private async Task<string> ReadRawBodyAsync()
    {
        Request.EnableBuffering();
        Request.Body.Position = 0;

        using var reader = new StreamReader(
            Request.Body,
            encoding: Encoding.UTF8,
            detectEncodingFromByteOrderMarks: false,
            leaveOpen: true);

        var body = await reader.ReadToEndAsync();

        // Remettre le curseur au début pour que le Controller puisse
        // relire le même corps de requête après ce Handler.
        Request.Body.Position = 0;

        return body;
    }

    private static string ComputeHmacSha256(string payload, byte[] secret)
    {
        using var hmac = new HMACSHA256(secret);
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(payload));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    /// <summary>
    /// Retire le préfixe optionnel "sha256=" si présent, pour accepter
    /// aussi bien "sha256=abc123..." (convention GitHub/Stripe) que
    /// juste "abc123..." selon ce que l'opérateur envoie réellement —
    /// le vrai format sera connu une fois un accord signé.
    /// </summary>
    private static string NormalizeSignature(string rawHeaderValue)
    {
        const string prefix = "sha256=";
        var trimmed = rawHeaderValue.Trim();
        return trimmed.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)
            ? trimmed[prefix.Length..].ToLowerInvariant()
            : trimmed.ToLowerInvariant();
    }

    /// <summary>
    /// Comparaison à temps constant — empêche une attaque par timing qui
    /// mesurerait le temps de réponse pour deviner la signature caractère
    /// par caractère. Ne JAMAIS utiliser == ou string.Equals pour comparer
    /// des signatures cryptographiques.
    /// </summary>
    private static bool ConstantTimeEquals(string expected, string provided)
    {
        var expectedBytes = Encoding.UTF8.GetBytes(expected);
        var providedBytes = Encoding.UTF8.GetBytes(provided);

        // CryptographicOperations.FixedTimeEquals exige des tableaux de même
        // longueur — si les longueurs diffèrent, la signature est de toute
        // façon invalide.
        if (expectedBytes.Length != providedBytes.Length)
            return false;

        return CryptographicOperations.FixedTimeEquals(expectedBytes, providedBytes);
    }
}