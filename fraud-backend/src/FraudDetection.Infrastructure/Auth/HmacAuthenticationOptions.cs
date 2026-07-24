using Microsoft.AspNetCore.Authentication;

namespace FraudDetection.Infrastructure.Auth;

/// <summary>
/// Options du schéma d'authentification HMAC — utilisé exclusivement pour
/// les webhooks opérateurs (TransactionController), jamais pour les humains
/// (AlertController, ReportController utilisent JwtAuthenticationHandler).
///
/// Enregistré dans Program.cs via :
///   .AddScheme&lt;HmacAuthenticationOptions, HmacAuthenticationHandler&gt;("Hmac", options => { ... })
/// </summary>
public sealed class HmacAuthenticationOptions : AuthenticationSchemeOptions
{
    /// <summary>
    /// Nom du header HTTP contenant la signature HMAC-SHA256 du corps
    /// de la requête, encodée en hexadécimal minuscule.
    /// Format attendu côté opérateur : sha256=&lt;hex_digest&gt;
    /// </summary>
    public string SignatureHeaderName { get; set; } = "X-Signature";

    /// <summary>
    /// Nom du header HTTP contenant l'horodatage Unix (secondes) auquel
    /// l'opérateur a signé la requête — utilisé pour la protection anti-replay,
    /// distinct de ReceivedAt (horodatage de réception côté .NET).
    /// </summary>
    public string TimestampHeaderName { get; set; } = "X-Timestamp";

    /// <summary>
    /// Nom du header HTTP contenant le code opérateur (ex: "BANKILY"),
    /// utilisé pour retrouver le secret HMAC correspondant via
    /// IOperatorSecretProvider.
    /// </summary>
    public string OperatorHeaderName { get; set; } = "X-Operator-Code";

    /// <summary>
    /// Tolérance maximale entre l'horodatage signé (X-Timestamp) et l'heure
    /// serveur actuelle — protection contre le replay d'une requête interceptée.
    /// Distinct de la fenêtre de 5 minutes déjà validée dans
    /// AnalyzeTransactionCommandValidator (qui porte sur ReceivedAt, l'heure
    /// de réception .NET, pas sur l'horodatage signé par l'opérateur).
    /// </summary>
    public TimeSpan ReplayWindow { get; set; } = TimeSpan.FromMinutes(5);
}