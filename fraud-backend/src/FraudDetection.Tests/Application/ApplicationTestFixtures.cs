using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Tests.Application;

/// <summary>
/// Helpers partagés par tous les tests de la couche Application.
/// Centralise la construction des objets de test pour éviter la duplication
/// et garantir que les tests restent lisibles.
/// </summary>
internal static class ApplicationTestFixtures
{
    // ── Constantes partagées ─────────────────────────────────────────────────
    public const string ValidOperatorCode = "BANKILY";
    public const string ValidTransactionId = "BNK-2024-001";
    public const string ValidAlertId = "ALT-C15FDD6C8FCB";
    public const string ValidCorrelationId = "corr-abc123def456";
    public const string ValidReviewedBy = "agent@bankily.mr";

    // ── Builders ─────────────────────────────────────────────────────────────

    public static Transaction BuildTransaction(
        string transactionId = ValidTransactionId,
        string operatorCode = ValidOperatorCode,
        decimal amount = 47000m,
        bool simChanged72h = false) =>
        new(
            transactionId: transactionId,
            clientToken: new TokenHash("a3f9b2c1d4e5f6a7"),
            amount: new Money(amount, "MRU"),
            channel: Channel.MobileApp,
            zone: "ROSSO",
            @operator: operatorCode,
            deviceId: new TokenHash("device123hash456"),
            simChanged72h: simChanged72h,
            simChangedAt: null,
            beneficiaryToken: new TokenHash("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: DateTime.UtcNow);

    public static RawWebhookPayload BuildPayload(
        string operatorCode = ValidOperatorCode,
        string? rawBody = null) =>
        new(
            operatorCode: operatorCode,
            rawBody: rawBody ?? """{"transaction_id":"BNK-2024-001","amount":47000}""",
            headers: new Dictionary<string, string>
            {
                ["X-Signature"] = "sha256=abc123",
                ["X-Timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString()
            },
            receivedAt: DateTimeOffset.UtcNow);

    public static RiskScore BuildApproveScore() =>
        new(score: 20, decision: DecisionStatus.Approve);

    public static RiskScore BuildReviewScore() =>
        new(score: 55, decision: DecisionStatus.Review,
            alertId: ValidAlertId, fraudType: "STRUCTURING");

    public static RiskScore BuildBlockScore() =>
        new(score: 87, decision: DecisionStatus.Block,
            alertId: ValidAlertId, fraudType: "SIM_SWAPPING");

    public static Alert BuildAlert(
        RiskScore? score = null,
        string alertId = ValidAlertId,
        string transactionId = ValidTransactionId,
        decimal amount = 47000m) =>
        new(
            alertId: alertId,
            transactionId: transactionId,
            @operator: ValidOperatorCode,
            score: score ?? BuildReviewScore(),
            amount: new Money(amount, "MRU"),
            createdAt: DateTime.UtcNow);
}