namespace FraudDetection.Infrastructure.Auth;

/// <summary>
/// Paramètres de validation JWT pour les sessions humaines (fraud-dashboard).
/// Lié à la section "Jwt" de la configuration (appsettings / variables
/// d'environnement) — voir JwtAuthenticationHandler.cs pour le câblage.
///
/// POINT OUVERT : le mécanisme d'ÉMISSION des tokens (login endpoint,
/// intégration avec un fournisseur d'identité externe, etc.) n'est pas
/// encore défini — ces options ne couvrent que la VALIDATION des tokens
/// côté API, pas leur émission. Un futur AuthController ou un IdP externe
/// (Keycloak, Azure AD, etc.) devra signer les tokens avec cette même clé
/// et ces mêmes issuer/audience.
/// </summary>
public sealed class JwtAuthenticationOptions
{
    public const string ConfigSectionName = "Jwt";

    /// <summary>Émetteur attendu du token — doit correspondre à ce que signe l'émetteur.</summary>
    public required string Issuer { get; init; }

    /// <summary>Audience attendue — identifie fraud-backend comme destinataire légitime.</summary>
    public required string Audience { get; init; }

    /// <summary>
    /// Clé symétrique de signature (HMAC-SHA256), en clair dans la config.
    /// JAMAIS commitée dans appsettings.json — uniquement via variable
    /// d'environnement / Kubernetes Secret en production, comme les
    /// secrets HMAC opérateurs (voir OperatorSecretProvider).
    /// Longueur minimale recommandée : 32 caractères (256 bits).
    /// </summary>
    public required string SigningKey { get; init; }

    /// <summary>
    /// Tolérance d'horloge entre le serveur ayant émis le token et ce serveur
    /// de validation. Volontairement réduite par rapport au défaut .NET (5 min)
    /// — les serveurs d'un même déploiement on-premise sont censés être
    /// synchronisés via NTP, une fenêtre large masquerait une dérive d'horloge
    /// anormale plutôt que de la révéler.
    /// </summary>
    public TimeSpan ClockSkew { get; init; } = TimeSpan.FromSeconds(30);

    /// <summary>
    /// Nom du claim JWT contenant le ou les rôles de l'agent
    /// (ex: "compliance_officer", "supervisor") — utilisé par les attributs
    /// [Authorize(Roles = "...")] sur AlertController et ReportController.
    /// </summary>
    public string RoleClaimType { get; init; } = "role";
}