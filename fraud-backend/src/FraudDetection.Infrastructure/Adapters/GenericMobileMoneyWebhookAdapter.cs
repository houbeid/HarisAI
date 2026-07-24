using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Infrastructure.Adapters;

/// <summary>
/// Payload webhook générique mobile money — schéma de test volontairement
/// neutre, non lié à un opérateur précis.
///
/// CONTEXTE : aucun accord n'est encore signé avec Bankily, Sedad ou Masrvi,
/// et aucun format de webhook réel n'a été obtenu d'aucun opérateur. Plutôt
/// que de coder un format hypothétique au nom d'un opérateur particulier
/// (ce qui donnerait une fausse impression de certitude), ce schéma sert
/// à valider tout le pipeline .NET → FastAPI dès maintenant, avec n'importe
/// quel code opérateur.
///
/// À LA SIGNATURE D'UN ACCORD : créer un adaptateur dédié (ex: BankilyWebhookAdapter)
/// reflétant le vrai format fourni par l'opérateur, l'enregistrer dans le DI
/// AVANT cet adaptateur générique — voir OperatorAdapterRegistry pour l'ordre
/// de résolution (spécifique prioritaire, générique en fallback).
/// </summary>
internal sealed class GenericMobileMoneyWebhookPayloadDto
{
    [JsonPropertyName("transaction_id")]
    public string? TransactionId { get; init; }

    /// <summary>Numéro de téléphone ou identifiant client réel — PII, à hasher avant usage.</summary>
    [JsonPropertyName("client_phone")]
    public string? ClientPhone { get; init; }

    [JsonPropertyName("amount")]
    public decimal Amount { get; init; }

    [JsonPropertyName("channel")]
    public string? Channel { get; init; }

    [JsonPropertyName("zone")]
    public string? Zone { get; init; }

    [JsonPropertyName("device_id")]
    public string? DeviceId { get; init; }

    [JsonPropertyName("sim_changed_72h")]
    public bool? SimChanged72h { get; init; }

    [JsonPropertyName("sim_changed_at")]
    public string? SimChangedAt { get; init; }

    [JsonPropertyName("beneficiary_phone")]
    public string? BeneficiaryPhone { get; init; }

    [JsonPropertyName("beneficiary_is_merchant")]
    public bool IsMerchantBeneficiary { get; init; }

    [JsonPropertyName("agent_id")]
    public string? AgentId { get; init; }

    [JsonPropertyName("timestamp")]
    public string? Timestamp { get; init; }
}

/// <summary>
/// Adaptateur générique — FALLBACK du registre, accepte n'importe quel
/// code opérateur tant qu'aucun adaptateur spécifique n'est enregistré
/// pour ce code précis.
///
/// PRIORITÉ DE RÉSOLUTION (voir OperatorAdapterRegistry) : un futur
/// adaptateur dédié à un opérateur précis (ex: BankilyWebhookAdapter,
/// une fois le vrai format connu) est TOUJOURS résolu en priorité —
/// cet adaptateur générique ne s'active que si aucun autre ne correspond.
///
/// USAGE : tests d'intégration, démonstrations, POC avec n'importe quel
/// opérateur avant signature d'un accord formel. Le schéma JSON accepté
/// est délibérément proche du contrat TransactionIn déjà connu côté
/// FastAPI, pour minimiser la traduction et faciliter les tests de bout
/// en bout dès aujourd'hui.
/// </summary>
public sealed class GenericMobileMoneyWebhookAdapter : IOperatorWebhookAdapter
{
    /// <summary>
    /// Accepte tout code opérateur non vide — c'est le comportement fallback
    /// voulu. OperatorAdapterRegistry garantit que cet adaptateur n'est
    /// consulté qu'en dernier recours, après tout adaptateur spécifique.
    /// </summary>
    public bool CanHandle(string operatorCode) =>
        !string.IsNullOrWhiteSpace(operatorCode);

    /// <summary>
    /// Marque explicitement cet adaptateur comme fallback générique —
    /// voir IOperatorWebhookAdapter.IsFallback pour le rôle exact de ce signal
    /// dans OperatorAdapterRegistry.
    /// </summary>
    public bool IsFallback => true;

    public Transaction Adapt(RawWebhookPayload payload)
    {
        GenericMobileMoneyWebhookPayloadDto dto;
        try
        {
            dto = JsonSerializer.Deserialize<GenericMobileMoneyWebhookPayloadDto>(payload.RawBody)
                  ?? throw new InvalidOperationException(
                      "Le payload générique désérialisé est vide.");
        }
        catch (JsonException ex)
        {
            throw new InvalidOperationException(
                $"Payload générique malformé pour l'opérateur {payload.OperatorCode} — JSON invalide.",
                ex);
        }

        if (string.IsNullOrWhiteSpace(dto.TransactionId))
            throw new InvalidOperationException(
                "Payload générique invalide — transaction_id manquant.");

        if (string.IsNullOrWhiteSpace(dto.ClientPhone))
            throw new InvalidOperationException(
                "Payload générique invalide — client_phone manquant.");

        var channel = MapChannel(dto.Channel);

        return new Transaction(
            transactionId: dto.TransactionId,
            clientToken: new TokenHash(Anonymize(dto.ClientPhone)),
            amount: new Money(dto.Amount, "MRU"),
            channel: channel,
            zone: dto.Zone ?? "INCONNU",
            @operator: payload.OperatorCode,
            deviceId: new TokenHash(AnonymizeDeviceId(dto.DeviceId)),
            simChanged72h: dto.SimChanged72h ?? false,
            simChangedAt: ParseOptionalTimestamp(dto.SimChangedAt),
            beneficiaryToken: new TokenHash(Anonymize(dto.BeneficiaryPhone ?? "INCONNU")),
            beneficiaryIsMerchant: dto.IsMerchantBeneficiary,
            agentId: string.IsNullOrWhiteSpace(dto.AgentId) ? null : dto.AgentId,
            ussdSession: channel == Channel.Ussd,
            timestamp: ParseTimestamp(dto.Timestamp));
    }

    private static Channel MapChannel(string? channel) => channel?.ToUpperInvariant() switch
    {
        "MOBILE_APP" => Channel.MobileApp,
        "USSD" => Channel.Ussd,
        "AGENT" => Channel.Agent,
        "MERCHANT" => Channel.Merchant,
        "ATM" => Channel.Atm,
        _ => throw new InvalidOperationException(
            $"Canal non reconnu dans le payload générique : '{channel}'. " +
            $"Valeurs acceptées : MOBILE_APP, USSD, AGENT, MERCHANT, ATM.")
    };

    private static DateTime ParseTimestamp(string? timestamp)
    {
        if (string.IsNullOrWhiteSpace(timestamp))
            throw new InvalidOperationException(
                "Payload générique invalide — timestamp manquant.");

        if (!DateTime.TryParse(
                timestamp,
                System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.AdjustToUniversal
                    | System.Globalization.DateTimeStyles.AssumeUniversal,
                out var parsed))
        {
            throw new InvalidOperationException(
                $"Payload générique invalide — timestamp illisible : '{timestamp}'.");
        }

        return parsed;
    }

    private static DateTime? ParseOptionalTimestamp(string? timestamp)
    {
        if (string.IsNullOrWhiteSpace(timestamp))
            return null;

        return DateTime.TryParse(
            timestamp,
            System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.AdjustToUniversal
                | System.Globalization.DateTimeStyles.AssumeUniversal,
            out var parsed)
            ? parsed
            : null;
    }

    /// <summary>
    /// Anonymise un numéro de téléphone via SHA-256. C'est la seule frontière
    /// où une donnée personnelle brute peut exister dans le système .NET —
    /// elle ne doit jamais atteindre le domaine, la base locale, ni FastAPI
    /// sous forme brute.
    /// </summary>
    private static string Anonymize(string rawValue)
    {
        var bytes = Encoding.UTF8.GetBytes(rawValue.Trim());
        var hash = SHA256.HashData(bytes);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static string AnonymizeDeviceId(string? deviceId)
    {
        if (string.IsNullOrWhiteSpace(deviceId))
            return Anonymize("DEVICE_INCONNU");

        bool looksAlreadyHashed = deviceId.Length == 64 && deviceId.All(Uri.IsHexDigit);

        return looksAlreadyHashed ? deviceId.ToLowerInvariant() : Anonymize(deviceId);
    }
}