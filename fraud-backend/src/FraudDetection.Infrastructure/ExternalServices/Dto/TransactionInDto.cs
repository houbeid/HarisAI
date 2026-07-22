using System.Text.Json.Serialization;

namespace FraudDetection.Infrastructure.ExternalServices.Dto;

/// <summary>
/// Miroir EXACT du schéma Pydantic TransactionIn (presentation/schemas.py côté Python).
/// CONTRAT FIGÉ — ne jamais modifier sans coordination avec fraud-ml-service.
///
/// Toute modification de ce fichier doit être accompagnée d'une modification
/// symétrique de FastApiContractTests.cs (WireMock) et d'une vérification
/// contre presentation/schemas.py côté Python.
///
/// RÔLE : ce DTO n'existe que pour la sérialisation JSON vers POST /analyze.
/// Il n'est jamais exposé en dehors de MlScoringService — le mapping
/// Transaction (domaine) → TransactionInDto se fait exclusivement dans
/// MlScoringService.AnalyzeAsync().
///
/// Noms de propriétés en snake_case via JsonPropertyName — le contrat Python
/// utilise ce format (transaction_id, client_token, etc.), pas le PascalCase .NET.
/// </summary>
public sealed class TransactionInDto
{
    [JsonPropertyName("transaction_id")]
    public required string TransactionId { get; init; }

    [JsonPropertyName("client_token")]
    public required string ClientToken { get; init; }

    [JsonPropertyName("amount")]
    public required decimal Amount { get; init; }

    [JsonPropertyName("currency")]
    public required string Currency { get; init; }

    [JsonPropertyName("channel")]
    public required string Channel { get; init; }

    [JsonPropertyName("zone")]
    public required string Zone { get; init; }

    [JsonPropertyName("operator")]
    public required string Operator { get; init; }

    [JsonPropertyName("device_id")]
    public required string DeviceId { get; init; }

    [JsonPropertyName("sim_changed_72h")]
    public required bool SimChanged72h { get; init; }

    /// <summary>
    /// Format ISO 8601 avec suffixe Z (UTC) — ex: "2024-01-15T02:30:00Z".
    /// Nullable côté Python si sim_changed_72h est false.
    /// </summary>
    [JsonPropertyName("sim_changed_at")]
    public string? SimChangedAt { get; init; }

    [JsonPropertyName("beneficiary_token")]
    public required string BeneficiaryToken { get; init; }

    [JsonPropertyName("beneficiary_is_merchant")]
    public required bool BeneficiaryIsMerchant { get; init; }

    /// <summary>Null si la transaction n'est pas via un agent physique.</summary>
    [JsonPropertyName("agent_id")]
    public string? AgentId { get; init; }

    [JsonPropertyName("ussd_session")]
    public required bool UssdSession { get; init; }

    /// <summary>Format ISO 8601 avec suffixe Z (UTC).</summary>
    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    /// <summary>
    /// Toujours null depuis .NET pour l'instant — réservé pour un futur usage
    /// où .NET pré-calculerait des features côté client avant l'appel FastAPI.
    /// Non utilisé dans le flux actuel.
    /// </summary>
    [JsonPropertyName("pre_computed_features")]
    public object? PreComputedFeatures { get; init; }
}