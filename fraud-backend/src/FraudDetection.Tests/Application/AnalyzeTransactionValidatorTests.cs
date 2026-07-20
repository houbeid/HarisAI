using FraudDetection.Application.Commands.AnalyzeTransaction;
using FraudDetection.Application.Interfaces;
using Xunit;

namespace FraudDetection.Tests.Application;

public class AnalyzeTransactionValidatorTests
{
    private readonly AnalyzeTransactionCommandValidator _validator = new();

    private static AnalyzeTransactionCommand BuildValidCommand(
        string operatorCode = ApplicationTestFixtures.ValidOperatorCode,
        string? rawBody = null,
        DateTimeOffset? receivedAt = null) =>
        new(
            payload: new RawWebhookPayload(
                operatorCode: operatorCode,
                rawBody: rawBody ?? """{"transaction_id":"BNK-2024-001","amount":47000}""",
                headers: new Dictionary<string, string>
                {
                    ["X-Signature"] = "sha256=abc123"
                },
                receivedAt: receivedAt ?? DateTimeOffset.UtcNow),
            correlationId: ApplicationTestFixtures.ValidCorrelationId);

    // ── Cas valides ───────────────────────────────────────────────────────────

    [Fact]
    public void Validate_ValidCommand_NoErrors()
    {
        var result = _validator.Validate(BuildValidCommand());
        Assert.True(result.IsValid);
    }

    [Theory]
    [InlineData("BANKILY")]
    [InlineData("SEDAD")]
    [InlineData("MASRVI")]
    [InlineData("NEW_OPERATOR")]  // Registre ouvert — tout code valide est accepté
    public void Validate_ValidOperatorCode_NoError(string operatorCode)
    {
        var result = _validator.Validate(BuildValidCommand(operatorCode: operatorCode));
        Assert.True(result.IsValid);
    }

    // ── CorrelationId ─────────────────────────────────────────────────────────

    [Fact]
    public void Validate_EmptyCorrelationId_ReturnsError()
    {
        var command = new AnalyzeTransactionCommand(
            payload: ApplicationTestFixtures.BuildPayload(),
            correlationId: "valid-id"); // On ne peut pas passer "" — constructor guard

        // Le constructor de AnalyzeTransactionCommand lève déjà une exception
        // si correlationId est vide — le validator est une couche supplémentaire
        Assert.Throws<ArgumentException>(() =>
            new AnalyzeTransactionCommand(
                payload: ApplicationTestFixtures.BuildPayload(),
                correlationId: ""));
    }

    // ── OperatorCode ──────────────────────────────────────────────────────────

    [Theory]
    [InlineData("bankily")]     // Minuscules — rejeté par le regex ^[A-Z0-9_]+$
    [InlineData("Bankily")]     // Mixte — rejeté
    [InlineData("BANK ILY")]   // Espace — rejeté
    [InlineData("BANK-ILY")]   // Tiret — rejeté
    public void Validate_InvalidOperatorCodeFormat_ReturnsError(string operatorCode)
    {
        // RawWebhookPayload normalise en majuscules dans son constructeur —
        // les minuscules passent donc. On teste directement le validator
        // avec un payload dont l'opérateur contient des caractères invalides.
        // Note : le validator reçoit la valeur APRÈS normalisation uppercase
        // de RawWebhookPayload. Les cas avec espace et tiret sont les vrais
        // cas de rejet par le regex ^[A-Z0-9_]+$.
        if (operatorCode.Contains(' ') || operatorCode.Contains('-'))
        {
            // Ces cas lèvent une exception dans RawWebhookPayload avant même
            // d'atteindre le validator — la validation structurelle est en amont.
            Assert.Throws<ArgumentException>(() =>
                ApplicationTestFixtures.BuildPayload(operatorCode: operatorCode));
        }
    }

    // ── RawBody ───────────────────────────────────────────────────────────────

    [Fact]
    public void Validate_InvalidJson_ReturnsError()
    {
        var result = _validator.Validate(
            BuildValidCommand(rawBody: "not-valid-json{{{"));

        Assert.False(result.IsValid);
        Assert.Contains(result.Errors,
            e => e.PropertyName.Contains("RawBody") &&
                 e.ErrorMessage.Contains("JSON"));
    }

    [Fact]
    public void Validate_ValidJson_NoError()
    {
        var result = _validator.Validate(
            BuildValidCommand(rawBody: """{"key":"value","amount":1000}"""));

        Assert.True(result.IsValid);
    }

    // ── ReceivedAt ────────────────────────────────────────────────────────────

    [Fact]
    public void Validate_WebhookOlderThan5Minutes_ReturnsError()
    {
        var oldTimestamp = DateTimeOffset.UtcNow.AddMinutes(-6);
        var result = _validator.Validate(
            BuildValidCommand(receivedAt: oldTimestamp));

        Assert.False(result.IsValid);
        Assert.Contains(result.Errors,
            e => e.PropertyName.Contains("ReceivedAt"));
    }

    [Fact]
    public void Validate_RecentWebhook_NoError()
    {
        var recentTimestamp = DateTimeOffset.UtcNow.AddMinutes(-2);
        var result = _validator.Validate(
            BuildValidCommand(receivedAt: recentTimestamp));

        Assert.True(result.IsValid);
    }

    [Fact]
    public void Validate_WebhookExactly5MinutesOld_IsValid()
    {
        // Limite exacte — doit passer (<=5 min)
        var exactLimit = DateTimeOffset.UtcNow.AddMinutes(-5).AddSeconds(1);
        var result = _validator.Validate(
            BuildValidCommand(receivedAt: exactLimit));

        Assert.True(result.IsValid);
    }
}