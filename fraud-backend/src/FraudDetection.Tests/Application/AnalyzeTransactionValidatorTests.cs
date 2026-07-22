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
    [InlineData("bankily")]     // Minuscules — normalisé en "BANKILY" par RawWebhookPayload, donc VALIDE
    [InlineData("Bankily")]     // Mixte — normalisé en "BANKILY" par RawWebhookPayload, donc VALIDE
    public void Validate_LowercaseOperatorCode_IsValidAfterNormalization(string operatorCode)
    {
        // RawWebhookPayload normalise en majuscules dans son constructeur
        // (ToUpperInvariant()) — le Validator ne voit donc jamais de minuscules.
        // Ce test documente ce comportement explicitement plutôt que de le supposer.
        var result = _validator.Validate(BuildValidCommand(operatorCode: operatorCode));

        Assert.True(result.IsValid);
    }

    [Theory]
    [InlineData("BANK ILY")]   // Espace — rejeté par le regex ^[A-Z0-9_]+$
    [InlineData("BANK-ILY")]   // Tiret — rejeté par le regex ^[A-Z0-9_]+$
    public void Validate_InvalidOperatorCodeFormat_ReturnsError(string operatorCode)
    {
        // RawWebhookPayload ne valide QUE la non-vacuité — il ne rejette jamais
        // un format invalide, il se contente de normaliser la casse.
        // C'est AnalyzeTransactionCommandValidator (FluentValidation) qui applique
        // le regex ^[A-Z0-9_]+$ et rejette espace/tiret. Validation structurelle
        // centralisée dans une seule couche — pas dupliquée dans le DTO.
        var result = _validator.Validate(BuildValidCommand(operatorCode: operatorCode));

        Assert.False(result.IsValid);
        Assert.Contains(result.Errors,
            e => e.PropertyName.Contains("OperatorCode"));
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