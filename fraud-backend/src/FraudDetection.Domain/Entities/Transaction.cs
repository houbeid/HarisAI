using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Domain.Entities;

/// <summary>
/// Transaction mobile money reçue depuis un opérateur via webhook.
/// Construite par l'adaptateur opérateur (BankilyWebhookAdapter, etc.)
/// après transformation du payload brut vers ce format normalisé.
///
/// CONTRAINTE : client_token et device_id sont des hashes anonymisés —
/// jamais de données personnelles brutes (numéro de téléphone, nom).
/// L'anonymisation est une responsabilité de l'adaptateur, pas du domaine.
/// </summary>
public sealed class Transaction
{
    public string TransactionId { get; }
    public TokenHash ClientToken { get; }
    public Money Amount { get; }
    public Channel Channel { get; }
    public string Zone { get; }

    /// <summary>
    /// Code opérateur — string, jamais enum, pour rester ouvert à l'extension
    /// sans modifier le domaine (registre d'adaptateurs).
    /// Valeurs actuelles : BANKILY, SEDAD, MASRVI.
    /// </summary>
    public string Operator { get; }

    public TokenHash DeviceId { get; }
    public bool SimChanged72h { get; }
    public DateTime? SimChangedAt { get; }
    public TokenHash BeneficiaryToken { get; }
    public bool BeneficiaryIsMerchant { get; }

    /// <summary>Code agent — null si la transaction n'est pas via un agent physique</summary>
    public string? AgentId { get; }

    public bool UssdSession { get; }
    public DateTime Timestamp { get; }

    public Transaction(
        string transactionId,
        TokenHash clientToken,
        Money amount,
        Channel channel,
        string zone,
        string @operator,
        TokenHash deviceId,
        bool simChanged72h,
        DateTime? simChangedAt,
        TokenHash beneficiaryToken,
        bool beneficiaryIsMerchant,
        string? agentId,
        bool ussdSession,
        DateTime timestamp)
    {
        if (string.IsNullOrWhiteSpace(transactionId))
            throw new ArgumentException("TransactionId ne peut pas être vide.", nameof(transactionId));

        if (string.IsNullOrWhiteSpace(zone))
            throw new ArgumentException("Zone ne peut pas être vide.", nameof(zone));

        if (string.IsNullOrWhiteSpace(@operator))
            throw new ArgumentException("Operator ne peut pas être vide.", nameof(@operator));

        // Cohérence métier : si le canal est USSD, ussdSession devrait être vrai
        // et inversement — signal détecté lors du croisement avec le contrat FastAPI
        if (channel == Channel.Ussd && !ussdSession)
            throw new ArgumentException(
                "Une transaction sur canal USSD doit avoir ussd_session=true.",
                nameof(ussdSession));

        // Cohérence métier : un agent_id ne peut être présent que sur canal AGENT
        if (agentId is not null && channel != Channel.Agent)
            throw new ArgumentException(
                $"AgentId ne peut être renseigné que sur le canal AGENT. Canal actuel : {channel}.",
                nameof(agentId));

        TransactionId = transactionId.Trim();
        ClientToken = clientToken;
        Amount = amount;
        Channel = channel;
        Zone = zone.Trim().ToUpperInvariant();
        Operator = @operator.Trim().ToUpperInvariant();
        DeviceId = deviceId;
        SimChanged72h = simChanged72h;
        SimChangedAt = simChangedAt;
        BeneficiaryToken = beneficiaryToken;
        BeneficiaryIsMerchant = beneficiaryIsMerchant;
        AgentId = agentId?.Trim();
        UssdSession = ussdSession;
        Timestamp = timestamp;
    }

    /// <summary>
    /// Vrai si le client envoie de l'argent à lui-même.
    /// Signal utilisé dans la détection de comportements suspects
    /// (test des limites de plafond, préparation d'un compte mule).
    /// </summary>
    public bool IsSelfTransfer => ClientToken.IsSameAs(BeneficiaryToken);

    /// <summary>
    /// Retourne une nouvelle Transaction identique avec sim_changed_72h corrigé.
    /// Utilisé exclusivement par ISimChangeService.EnrichAsync() quand l'opérateur
    /// ne fournit pas cette information dans son webhook et qu'une source télécom
    /// locale permet de la calculer.
    ///
    /// Tous les autres champs sont préservés à l'identique — pas de revalidation
    /// des cohérences métier (channel/ussdSession, agentId/channel) car la transaction
    /// a déjà passé le constructeur avec succès.
    /// </summary>
    public Transaction WithSimChanged72h(bool simChanged72h, DateTime? simChangedAt = null) =>
        new(
            transactionId: TransactionId,
            clientToken: ClientToken,
            amount: Amount,
            channel: Channel,
            zone: Zone,
            @operator: Operator,
            deviceId: DeviceId,
            simChanged72h: simChanged72h,
            simChangedAt: simChangedAt ?? SimChangedAt,
            beneficiaryToken: BeneficiaryToken,
            beneficiaryIsMerchant: BeneficiaryIsMerchant,
            agentId: AgentId,
            ussdSession: UssdSession,
            timestamp: Timestamp);

    public override string ToString() =>
        $"[{TransactionId}] {Amount} via {Channel} — Operator={Operator}";
}