using System.Text;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Infrastructure.Auth;

/// <summary>
/// Implémentation de IOperatorSecretProvider — lit les secrets HMAC depuis
/// la configuration .NET standard (IConfiguration), qui résout automatiquement
/// appsettings.json, variables d'environnement, et tout autre provider
/// configuré dans Program.cs (Kubernetes Secrets montés en variables
/// d'environnement en production — voir kubernetes/overlays/{site}/).
///
/// CONVENTION DE CLÉ : "OperatorSecrets:{OPERATOR_CODE}" (majuscules).
/// Exemple appsettings.Development.json (jamais commité avec de vrais secrets) :
///   {
///     "OperatorSecrets": {
///       "BANKILY": "dev-secret-never-use-in-prod"
///     }
///   }
///
/// En production, ces valeurs viennent exclusivement de variables
/// d'environnement injectées par l'IT de la banque (Kubernetes Secret),
/// jamais du fichier appsettings.json versionné dans le repo.
/// </summary>
public sealed class OperatorSecretProvider : IOperatorSecretProvider
{
    private const string ConfigSectionName = "OperatorSecrets";
    private const int MinimumSecretLength = 16;

    private readonly IConfiguration _configuration;
    private readonly ILogger<OperatorSecretProvider> _logger;

    public OperatorSecretProvider(
        IConfiguration configuration,
        ILogger<OperatorSecretProvider> logger)
    {
        _configuration = configuration;
        _logger = logger;
    }

    public byte[]? GetSecret(string operatorCode)
    {
        if (string.IsNullOrWhiteSpace(operatorCode))
            return null;

        var normalizedCode = operatorCode.Trim().ToUpperInvariant();
        var configKey = $"{ConfigSectionName}:{normalizedCode}";
        var secretValue = _configuration[configKey];

        if (string.IsNullOrEmpty(secretValue))
        {
            _logger.LogError(
                "Aucun secret HMAC configuré pour l'opérateur {OperatorCode} " +
                "(clé attendue : {ConfigKey}). Vérifier appsettings ou les " +
                "variables d'environnement du déploiement.",
                normalizedCode, configKey);
            return null;
        }

        // Garde défensive — un secret trop court affaiblirait significativement
        // la sécurité HMAC. Ne bloque pas le démarrage (pourrait être un secret
        // de test local), mais alerte fortement.
        if (secretValue.Length < MinimumSecretLength)
        {
            _logger.LogWarning(
                "Le secret HMAC configuré pour {OperatorCode} fait moins de " +
                "{MinimumLength} caractères — risque de sécurité. " +
                "Générer un secret plus long pour la production.",
                normalizedCode, MinimumSecretLength);
        }

        return Encoding.UTF8.GetBytes(secretValue);
    }
}